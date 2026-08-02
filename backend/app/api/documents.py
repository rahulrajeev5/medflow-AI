import io
import json
import re
import time
import uuid
from pathlib import Path

import boto3
import fitz
import pytesseract
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal, get_db
from app.models.document import Document, DocumentStatus
from app.schemas.document import DocumentListItem, DocumentRead

router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()

pytesseract.pytesseract.tesseract_cmd = settings.tesseract_path

AWS_PROFILE = "medflow"
AWS_REGION = "eu-central-1"
BEDROCK_MODEL_ID = "eu.amazon.nova-2-lite-v1:0"

ALLOWED_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
}


def extract_text_from_image(file_path: str) -> str:
    """Extract text from a PNG or JPEG image using Tesseract."""

    with Image.open(file_path) as image:
        image = image.convert("RGB")
        return pytesseract.image_to_string(image).strip()


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from each PDF page using Tesseract OCR."""

    extracted_pages: list[str] = []

    with fitz.open(file_path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            pixmap = page.get_pixmap(dpi=200)
            image_bytes = pixmap.tobytes("png")

            with Image.open(io.BytesIO(image_bytes)) as image:
                image = image.convert("RGB")
                page_text = pytesseract.image_to_string(image).strip()

            if page_text:
                extracted_pages.append(
                    f"--- Page {page_number} ---\n{page_text}"
                )

    return "\n\n".join(extracted_pages)


def extract_document_text(document: Document) -> str:
    """Select the OCR method based on the uploaded content type."""

    if document.content_type == "application/pdf":
        return extract_text_from_pdf(document.file_path)

    if document.content_type in {"image/png", "image/jpeg"}:
        return extract_text_from_image(document.file_path)

    raise ValueError(
        f"Unsupported content type: {document.content_type}"
    )


def extract_json_from_response(output_text: str) -> dict:
    """
    Parse JSON returned by Bedrock.

    Handles:
    - plain JSON
    - JSON inside Markdown code fences
    - explanatory text surrounding a JSON object
    """

    cleaned_text = output_text.strip()

    cleaned_text = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned_text,
        flags=re.IGNORECASE,
    )
    cleaned_text = re.sub(
        r"\s*```$",
        "",
        cleaned_text,
    )

    try:
        parsed = json.loads(cleaned_text)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict):
        return parsed

    start_index = cleaned_text.find("{")
    end_index = cleaned_text.rfind("}")

    if start_index == -1 or end_index == -1:
        raise ValueError(
            "Bedrock returned no JSON object. "
            f"Raw response: {output_text}"
        )

    json_text = cleaned_text[start_index : end_index + 1]

    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Bedrock returned malformed JSON. "
            f"Raw response: {output_text}"
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError(
            "Bedrock JSON response must be an object."
        )

    return parsed


def analyze_with_bedrock(ocr_text: str) -> dict:
    """Use Amazon Bedrock to summarize and structure OCR text."""

    session = boto3.Session(
        profile_name=AWS_PROFILE,
        region_name=AWS_REGION,
    )

    client = session.client("bedrock-runtime")

    prompt = f"""
Analyze the OCR text from a healthcare-related document.

Return exactly one valid JSON object with this structure:

{{
  "document_type": "string",
  "patient_name": null,
  "doctor": null,
  "department": null,
  "priority": "unknown",
  "summary": "short factual summary",
  "confidence": 0.0
}}

Requirements:

- Return only one JSON object.
- Do not wrap the JSON in Markdown.
- Do not include explanations before or after the JSON.
- Do not provide medical advice.
- Do not invent information.
- Use null when information is not present.
- priority must be one of:
  "low", "medium", "high", or "unknown".
- confidence must be a number between 0 and 1.
- The summary must remain factual and concise.

OCR text:

{ocr_text[:12000]}
"""

    try:
        response = client.converse(
            modelId=BEDROCK_MODEL_ID,
            system=[
                {
                    "text": (
                        "You extract structured information from documents. "
                        "Your complete response must be one valid JSON object."
                    )
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": prompt,
                        }
                    ],
                }
            ],
            inferenceConfig={
                "maxTokens": 600,
                "temperature": 0,
                "topP": 0.9,
            },
        )

        content = response["output"]["message"]["content"]

        output_text = "".join(
            item.get("text", "")
            for item in content
            if "text" in item
        ).strip()

        if not output_text:
            raise ValueError(
                "Bedrock returned an empty response."
            )

        print("\nRaw Bedrock response:")
        print(output_text)
        print("\nBedrock token usage:")
        print(response.get("usage", {}))

        return extract_json_from_response(output_text)

    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(
            f"Bedrock request failed: {exc}"
        ) from exc


def normalize_priority(value: object) -> str:
    """Ensure priority is one of the supported values."""

    if not isinstance(value, str):
        return "unknown"

    priority = value.strip().lower()

    if priority not in {
        "low",
        "medium",
        "high",
        "unknown",
    }:
        return "unknown"

    return priority


def normalize_confidence(value: object) -> float | None:
    """Ensure confidence is a number between zero and one."""

    if isinstance(value, bool):
        return None

    if not isinstance(value, (int, float)):
        return None

    return max(0.0, min(float(value), 1.0))


def process_document(document_id: uuid.UUID) -> None:
    """
    Run OCR and Bedrock analysis in a FastAPI background task.

    This will later be replaced by SQS and a processing Lambda.
    """

    started_at = time.perf_counter()

    try:
        with SessionLocal() as db:
            document = db.get(Document, document_id)

            if not document:
                return

            document.status = DocumentStatus.processing
            document.error_message = None
            db.commit()

        with SessionLocal() as db:
            document = db.get(Document, document_id)

            if not document:
                return

            extracted_text = extract_document_text(document)

            if not extracted_text.strip():
                raise ValueError(
                    "OCR completed, but no readable text was detected."
                )

            ai_result = analyze_with_bedrock(extracted_text)

            document_type = ai_result.get("document_type")

            if not isinstance(document_type, str):
                document_type = "Medical Document"

            summary = ai_result.get("summary")

            if not isinstance(summary, str) or not summary.strip():
                summary = "No summary generated."

            document.document_type = document_type
            document.ocr_text = extracted_text
            document.ai_summary = summary

            document.structured_data = {
                "patient_name": ai_result.get("patient_name"),
                "doctor": ai_result.get("doctor"),
                "department": ai_result.get("department"),
                "priority": normalize_priority(
                    ai_result.get("priority")
                ),
                "confidence": normalize_confidence(
                    ai_result.get("confidence")
                ),
                "ocr_character_count": len(extracted_text),
                "ocr_word_count": len(extracted_text.split()),
                "requires_human_review": True,
            }

            document.processing_time_ms = int(
                (time.perf_counter() - started_at) * 1000
            )
            document.status = DocumentStatus.completed
            document.error_message = None

            db.commit()

    except Exception as exc:
        print(
            f"\nDocument processing failed for {document_id}:"
        )
        print(repr(exc))

        with SessionLocal() as db:
            document = db.get(Document, document_id)

            if not document:
                return

            document.status = DocumentStatus.failed
            document.error_message = str(exc)
            document.processing_time_ms = int(
                (time.perf_counter() - started_at) * 1000
            )

            db.commit()


@router.post(
    "",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF, PNG, and JPEG documents are supported.",
        )

    settings.upload_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    document_id = uuid.uuid4()

    original_filename = file.filename or "document"
    safe_suffix = Path(original_filename).suffix.lower()

    if not safe_suffix:
        safe_suffix = {
            "application/pdf": ".pdf",
            "image/png": ".png",
            "image/jpeg": ".jpg",
        }.get(file.content_type, "")

    destination = (
        settings.upload_dir
        / f"{document_id}{safe_suffix}"
    )

    size = 0

    try:
        with destination.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)

                if size > max_bytes:
                    destination.unlink(missing_ok=True)

                    raise HTTPException(
                        status_code=(
                            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
                        ),
                        detail=(
                            f"File exceeds the "
                            f"{settings.max_upload_mb} MB limit."
                        ),
                    )

                output.write(chunk)

    finally:
        file.file.close()

    document = Document(
        id=document_id,
        filename=original_filename,
        content_type=file.content_type,
        file_path=str(destination),
        size_bytes=size,
        status=DocumentStatus.uploaded,
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    background_tasks.add_task(
        process_document,
        document.id,
    )

    return document


@router.get(
    "",
    response_model=list[DocumentListItem],
)
def list_documents(
    db: Session = Depends(get_db),
):
    statement = (
        select(Document)
        .order_by(Document.created_at.desc())
    )

    return list(
        db.scalars(statement).all()
    )


@router.get(
    "/{document_id}",
    response_model=DocumentRead,
)
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    document = db.get(
        Document,
        document_id,
    )

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    return document