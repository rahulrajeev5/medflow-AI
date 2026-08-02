import io
import json
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
import fitz
import pytesseract
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from app.services.sqs import send_processing_message
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

BEDROCK_MODEL_ID = "eu.amazon.nova-2-lite-v1:0"

ALLOWED_TYPES = {"application/pdf", "image/png", "image/jpeg"}
CONTENT_TYPE_SUFFIXES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


def get_aws_session() -> boto3.Session:
    return boto3.Session(
        profile_name=settings.aws_profile,
        region_name=settings.aws_region,
    )


def get_s3_client():
    return get_aws_session().client("s3")


def get_bedrock_client():
    bedrock_region = getattr(settings, "bedrock_region", settings.aws_region)
    return boto3.Session(
        profile_name=settings.aws_profile,
        region_name=bedrock_region,
    ).client("bedrock-runtime")


def build_s3_key(document_id: uuid.UUID, filename: str, content_type: str) -> str:
    suffix = Path(filename).suffix.lower() or CONTENT_TYPE_SUFFIXES.get(content_type, "")
    current_date = datetime.now(timezone.utc)
    return (
        f"documents/{current_date.year}/"
        f"{current_date.month:02d}/{document_id}{suffix}"
    )


def upload_file_to_s3(local_path: Path, s3_key: str, content_type: str) -> None:
    get_s3_client().upload_file(
        Filename=str(local_path),
        Bucket=settings.s3_bucket_name,
        Key=s3_key,
        ExtraArgs={"ContentType": content_type},
    )


def download_file_from_s3(s3_key: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    get_s3_client().download_file(
        settings.s3_bucket_name,
        s3_key,
        str(destination),
    )


def delete_file_from_s3(s3_key: str) -> None:
    get_s3_client().delete_object(
        Bucket=settings.s3_bucket_name,
        Key=s3_key,
    )


def extract_text_from_image(file_path: str) -> str:
    with Image.open(file_path) as image:
        return pytesseract.image_to_string(image.convert("RGB")).strip()


def extract_text_from_pdf(file_path: str) -> str:
    extracted_pages: list[str] = []
    with fitz.open(file_path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            pixmap = page.get_pixmap(dpi=200)
            with Image.open(io.BytesIO(pixmap.tobytes("png"))) as image:
                page_text = pytesseract.image_to_string(image.convert("RGB")).strip()
            if page_text:
                extracted_pages.append(f"--- Page {page_number} ---\n{page_text}")
    return "\n\n".join(extracted_pages)


def extract_document_text(file_path: Path, content_type: str) -> str:
    if content_type == "application/pdf":
        return extract_text_from_pdf(str(file_path))
    if content_type in {"image/png", "image/jpeg"}:
        return extract_text_from_image(str(file_path))
    raise ValueError(f"Unsupported content type: {content_type}")


def extract_json_from_response(output_text: str) -> dict[str, Any]:
    cleaned_text = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        output_text.strip(),
        flags=re.IGNORECASE,
    )

    try:
        parsed = json.loads(cleaned_text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start_index = cleaned_text.find("{")
    end_index = cleaned_text.rfind("}")
    if start_index == -1 or end_index == -1 or end_index < start_index:
        raise ValueError(f"Bedrock returned no JSON object. Raw response: {output_text}")

    try:
        parsed = json.loads(cleaned_text[start_index : end_index + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Bedrock returned malformed JSON. Raw response: {output_text}"
        ) from exc

    if not isinstance(parsed, dict):
        raise ValueError("Bedrock JSON response must be an object.")
    return parsed


def analyze_with_bedrock(ocr_text: str) -> dict[str, Any]:
    client = get_bedrock_client()
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
- priority must be one of "low", "medium", "high", or "unknown".
- confidence must be between 0 and 1.

OCR text:
{ocr_text[:12000]}
"""

    try:
        response = client.converse(
            modelId=BEDROCK_MODEL_ID,
            system=[{
                "text": (
                    "You extract structured information from documents. "
                    "Your complete response must be one valid JSON object."
                )
            }],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 600, "temperature": 0, "topP": 0.9},
        )
        content = response["output"]["message"]["content"]
        output_text = "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and "text" in item
        ).strip()
        if not output_text:
            raise ValueError("Bedrock returned an empty response.")

        print("\nRaw Bedrock response:")
        print(output_text)
        print("\nBedrock token usage:")
        print(response.get("usage", {}))
        return extract_json_from_response(output_text)
    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(f"Bedrock request failed: {exc}") from exc


def normalize_priority(value: object) -> str:
    if not isinstance(value, str):
        return "unknown"
    priority = value.strip().lower()
    return priority if priority in {"low", "medium", "high", "unknown"} else "unknown"


def normalize_confidence(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(float(value), 1.0))


def process_document(document_id: uuid.UUID) -> None:
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

            suffix = Path(document.filename).suffix.lower() or CONTENT_TYPE_SUFFIXES.get(
                document.content_type,
                "",
            )

            with tempfile.TemporaryDirectory() as temp_dir:
                temporary_file = Path(temp_dir) / f"{document.id}{suffix}"
                download_file_from_s3(document.file_path, temporary_file)
                extracted_text = extract_document_text(
                    temporary_file,
                    document.content_type,
                )

            if not extracted_text.strip():
                raise ValueError("OCR completed, but no readable text was detected.")

            ai_result = analyze_with_bedrock(extracted_text)
            document_type = ai_result.get("document_type")
            if not isinstance(document_type, str) or not document_type.strip():
                document_type = "Medical Document"

            summary = ai_result.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                summary = "No summary generated."

            document.document_type = document_type.strip()
            document.ocr_text = extracted_text
            document.ai_summary = summary.strip()
            document.structured_data = {
                "patient_name": ai_result.get("patient_name"),
                "doctor": ai_result.get("doctor"),
                "department": ai_result.get("department"),
                "priority": normalize_priority(ai_result.get("priority")),
                "confidence": normalize_confidence(ai_result.get("confidence")),
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
        print(f"\nDocument processing failed for {document_id}:")
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


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
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

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    document_id = uuid.uuid4()
    original_filename = file.filename or "document"
    safe_suffix = Path(original_filename).suffix.lower() or CONTENT_TYPE_SUFFIXES.get(
        file.content_type,
        "",
    )
    temporary_destination = settings.upload_dir / f"{document_id}{safe_suffix}"
    s3_key = build_s3_key(document_id, original_filename, file.content_type)
    size = 0
    uploaded_to_s3 = False

    try:
        with temporary_destination.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds the {settings.max_upload_mb} MB limit.",
                    )
                output.write(chunk)

        upload_file_to_s3(
            local_path=temporary_destination,
            s3_key=s3_key,
            content_type=file.content_type,
        )
        uploaded_to_s3 = True

    except HTTPException:
        raise
    except (ClientError, BotoCoreError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"S3 upload failed: {exc}",
        ) from exc
    finally:
        file.file.close()
        temporary_destination.unlink(missing_ok=True)

    document = Document(
        id=document_id,
        filename=original_filename,
        content_type=file.content_type,
        file_path=s3_key,
        size_bytes=size,
        status=DocumentStatus.uploaded,
    )

    try:
        db.add(document)
        db.commit()
        db.refresh(document)
    except Exception:
        db.rollback()
        if uploaded_to_s3:
            try:
                delete_file_from_s3(s3_key)
            except Exception as cleanup_error:
                print("Unable to remove S3 object after database failure:", repr(cleanup_error))
        raise

    send_processing_message(document.id)
    return document


@router.get("", response_model=list[DocumentListItem])
def list_documents(db: Session = Depends(get_db)):
    statement = select(Document).order_by(Document.created_at.desc())
    return list(db.scalars(statement).all())


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return document