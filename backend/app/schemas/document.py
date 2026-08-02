import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.document import DocumentStatus


class DocumentRead(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    document_type: str | None
    ocr_text: str | None
    ai_summary: str | None
    structured_data: dict | None
    error_message: str | None
    processing_time_ms: int | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentListItem(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    document_type: str | None
    processing_time_ms: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
