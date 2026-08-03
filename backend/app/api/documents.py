import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.document import Document, DocumentStatus
from app.schemas.document import DocumentListItem, DocumentRead
from app.services.sqs import send_processing_message
from typing import Any



router = APIRouter(prefix="/documents", tags=["documents"])
settings = get_settings()

ALLOWED_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
}

CONTENT_TYPE_SUFFIXES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}


def get_aws_session() -> boto3.Session:
    """
    Use the standard AWS credential chain.

    Locally, set AWS_PROFILE=medflow.
    In AWS, boto3 automatically uses the execution role.
    """
    return boto3.Session(region_name=settings.aws_region)


def get_s3_client():
    return get_aws_session().client("s3")


def build_s3_key(
    document_id: uuid.UUID,
    filename: str,
    content_type: str,
) -> str:
    suffix = (
        Path(filename).suffix.lower()
        or CONTENT_TYPE_SUFFIXES.get(content_type, "")
    )
    current_date = datetime.now(timezone.utc)

    return (
        f"documents/"
        f"{current_date.year}/"
        f"{current_date.month:02d}/"
        f"{document_id}{suffix}"
    )


def upload_file_to_s3(
    local_path: Path,
    s3_key: str,
    content_type: str,
) -> None:
    get_s3_client().upload_file(
        Filename=str(local_path),
        Bucket=settings.s3_bucket_name,
        Key=s3_key,
        ExtraArgs={"ContentType": content_type},
    )


def delete_file_from_s3(s3_key: str) -> None:
    get_s3_client().delete_object(
        Bucket=settings.s3_bucket_name,
        Key=s3_key,
    )


@router.post(
    "",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_document(
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

    safe_suffix = (
        Path(original_filename).suffix.lower()
        or CONTENT_TYPE_SUFFIXES.get(file.content_type, "")
    )

    temporary_destination = (
        settings.upload_dir
        / f"{document_id}{safe_suffix}"
    )

    s3_key = build_s3_key(
        document_id=document_id,
        filename=original_filename,
        content_type=file.content_type,
    )

    size = 0
    uploaded_to_s3 = False
    document_saved = False

    try:
        with temporary_destination.open("wb") as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)

                if size > max_bytes:
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

        upload_file_to_s3(
            local_path=temporary_destination,
            s3_key=s3_key,
            content_type=file.content_type,
        )
        uploaded_to_s3 = True

        document = Document(
            id=document_id,
            filename=original_filename,
            content_type=file.content_type,
            file_path=s3_key,
            size_bytes=size,
            status=DocumentStatus.uploaded,
        )

        db.add(document)
        db.commit()
        db.refresh(document)
        document_saved = True

        try:
            send_processing_message(document.id)
        except Exception as exc:
            document.status = DocumentStatus.failed
            document.error_message = (
                f"Unable to enqueue processing job: {exc}"
            )
            db.commit()

            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Document uploaded, but queueing failed.",
            ) from exc

        return document

    except HTTPException:
        raise

    except (ClientError, BotoCoreError) as exc:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AWS operation failed: {exc}",
        ) from exc

    except Exception:
        db.rollback()
        raise

    finally:
        file.file.close()
        temporary_destination.unlink(missing_ok=True)

        if uploaded_to_s3 and not document_saved:
            try:
                delete_file_from_s3(s3_key)
            except Exception as cleanup_error:
                print(
                    "Unable to remove S3 object after failure:",
                    repr(cleanup_error),
                )


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
    document = db.get(Document, document_id)

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    return document