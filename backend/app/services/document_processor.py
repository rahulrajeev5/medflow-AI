import io
import json
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import boto3
import fitz
import pytesseract
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.document import Document, DocumentStatus

settings = get_settings()
import os


if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
    pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
else:
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_path

import os
import shutil

tesseract_binary = shutil.which("tesseract")

if tesseract_binary:
    pytesseract.pytesseract.tesseract_cmd = tesseract_binary
else:
    pytesseract.pytesseract.tesseract_cmd = settings.tesseract_path

BEDROCK_MODEL_ID = "eu.amazon.nova-2-lite-v1:0"

CONTENT_TYPE_SUFFIXES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


def get_aws_session(
    region_name: str | None = None,
) -> boto3.Session:
    """
    Use the standard AWS credential chain.

    Locally:
        export AWS_PROFILE=medflow

    In Lambda:
        boto3 automatically uses the Lambda execution role.
    """
    return boto3.Session(
        region_name=region_name or settings.aws_region,
    )


def get_s3_client():
    return get_aws_session(
        settings.aws_region
    ).client("s3")


def get_bedrock_client():
    return get_aws_session(
        settings.bedrock_region
    ).client("bedrock-runtime")


def download_file_from_s3(
    s3_key: str,
    destination: Path,
) -> None:
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    get_s3_client().download_file(
        settings.s3_bucket_name,
        s3_key,
        str(destination),
    )


def extract_text_from_image(
    file_path: Path,
) -> str:
    with Image.open(file_path) as image:
        image = image.convert("RGB")
        return pytesseract.image_to_string(
            image
        ).strip()


def extract_text_from_pdf(
    file_path: Path,
) -> str:
    extracted_pages: list[str] = []

    with fitz.open(file_path) as pdf:
        for page_number, page in enumerate(
            pdf,
            start=1,
        ):
            pixmap = page.get_pixmap(dpi=200)
            image_bytes = pixmap.tobytes("png")

            with Image.open(
                io.BytesIO(image_bytes)
            ) as image:
                image = image.convert("RGB")
                page_text = (
                    pytesseract.image_to_string(
                        image
                    ).strip()
                )

            if page_text:
                extracted_pages.append(
                    f"--- Page {page_number} ---\n"
                    f"{page_text}"
                )

    return "\n\n".join(extracted_pages)


def extract_document_text(
    file_path: Path,
    content_type: str,
) -> str:
    if content_type == "application/pdf":
        return extract_text_from_pdf(file_path)

    if content_type in {
        "image/png",
        "image/jpeg",
    }:
        return extract_text_from_image(file_path)

    raise ValueError(
        f"Unsupported content type: {content_type}"
    )


def extract_json_from_response(
    output_text: str,
) -> dict[str, Any]:
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

    if (
        start_index == -1
        or end_index == -1
        or end_index < start_index
    ):
        raise ValueError(
            "Bedrock returned no JSON object. "
            f"Raw response: {output_text}"
        )

    json_text = cleaned_text[
        start_index : end_index + 1
    ]

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


def analyze_with_bedrock(
    ocr_text: str,
) -> dict[str, Any]:
    prompt = f"""
Analyze the OCR text from a healthcare-related document.

Return exactly one valid JSON object:

{{
  "document_type": "string",
  "patient_name": null,
  "doctor": null,
  "department": null,
  "priority": "unknown",
  "summary": "short factual summary",
  "confidence": 0.0
}}

Rules:
- Return JSON only.
- Do not provide medical advice.
- Do not invent information.
- Use null when information is unavailable.
- priority must be low, medium, high, or unknown.
- confidence must be between 0 and 1.

OCR text:

{ocr_text[:12000]}
"""

    try:
        response = get_bedrock_client().converse(
            modelId=BEDROCK_MODEL_ID,
            system=[
                {
                    "text": (
                        "Extract structured information "
                        "from documents. Return one valid "
                        "JSON object only."
                    )
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
            inferenceConfig={
                "maxTokens": 600,
                "temperature": 0,
                "topP": 0.9,
            },
        )

        content = response[
            "output"
        ]["message"]["content"]

        output_text = "".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict)
            and "text" in item
        ).strip()

        if not output_text:
            raise ValueError(
                "Bedrock returned an empty response."
            )

        print("\nRaw Bedrock response:")
        print(output_text)
        print("\nBedrock token usage:")
        print(response.get("usage", {}))

        return extract_json_from_response(
            output_text
        )

    except (ClientError, BotoCoreError) as exc:
        raise RuntimeError(
            f"Bedrock request failed: {exc}"
        ) from exc


def normalize_priority(
    value: object,
) -> str:
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


def normalize_confidence(
    value: object,
) -> float | None:
    if isinstance(value, bool):
        return None

    if not isinstance(value, (int, float)):
        return None

    return max(
        0.0,
        min(float(value), 1.0),
    )


def process_document(
    document_id: uuid.UUID,
) -> None:
    """
    Download the S3 object, run OCR and Bedrock,
    and update RDS.

    Raises on failure so SQS and Lambda can retry.
    """
    started_at = time.perf_counter()

    try:
        with SessionLocal() as db:
            document = db.get(
                Document,
                document_id,
            )

            if not document:
                raise ValueError(
                    f"Document {document_id} "
                    "was not found."
                )

            document.status = (
                DocumentStatus.processing
            )
            document.error_message = None
            db.commit()

        with SessionLocal() as db:
            document = db.get(
                Document,
                document_id,
            )

            if not document:
                raise ValueError(
                    f"Document {document_id} "
                    "was not found."
                )

            suffix = (
                Path(
                    document.filename
                ).suffix.lower()
                or CONTENT_TYPE_SUFFIXES.get(
                    document.content_type,
                    "",
                )
            )

            with tempfile.TemporaryDirectory() as temp_dir:
                temporary_file = (
                    Path(temp_dir)
                    / f"{document.id}{suffix}"
                )

                download_file_from_s3(
                    s3_key=document.file_path,
                    destination=temporary_file,
                )

                extracted_text = (
                    extract_document_text(
                        file_path=temporary_file,
                        content_type=(
                            document.content_type
                        ),
                    )
                )

            if not extracted_text.strip():
                raise ValueError(
                    "OCR completed, but no readable "
                    "text was detected."
                )

            ai_result = analyze_with_bedrock(
                extracted_text
            )

            document_type = ai_result.get(
                "document_type"
            )

            if (
                not isinstance(
                    document_type,
                    str,
                )
                or not document_type.strip()
            ):
                document_type = (
                    "Medical Document"
                )

            summary = ai_result.get("summary")

            if (
                not isinstance(summary, str)
                or not summary.strip()
            ):
                summary = "No summary generated."

            document.document_type = (
                document_type.strip()
            )
            document.ocr_text = extracted_text
            document.ai_summary = summary.strip()

            document.structured_data = {
                "patient_name": ai_result.get(
                    "patient_name"
                ),
                "doctor": ai_result.get("doctor"),
                "department": ai_result.get(
                    "department"
                ),
                "priority": normalize_priority(
                    ai_result.get("priority")
                ),
                "confidence": normalize_confidence(
                    ai_result.get("confidence")
                ),
                "ocr_character_count": len(
                    extracted_text
                ),
                "ocr_word_count": len(
                    extracted_text.split()
                ),
                "requires_human_review": True,
            }

            document.processing_time_ms = int(
                (
                    time.perf_counter()
                    - started_at
                )
                * 1000
            )
            document.status = (
                DocumentStatus.completed
            )
            document.error_message = None
            db.commit()

    except Exception as exc:
        with SessionLocal() as db:
            document = db.get(
                Document,
                document_id,
            )

            if document:
                document.status = (
                    DocumentStatus.failed
                )
                document.error_message = str(exc)
                document.processing_time_ms = int(
                    (
                        time.perf_counter()
                        - started_at
                    )
                    * 1000
                )
                db.commit()

        raise