from functools import lru_cache
from pathlib import Path
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MedFlow AI API"

    database_url: str | None = None
    db_secret_name: str | None = None

    upload_dir: Path = Path(
    "/tmp/uploads"
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME")
    else "uploads"
)
    max_upload_mb: int = 10

    allowed_origins: list[str] = [
    "http://localhost:5173",
    "https://d1d8yct7oy0z3l.cloudfront.net",
]

    aws_profile: str | None = None
    aws_region: str = "eu-central-1"
    bedrock_region: str = "eu-central-1"

    s3_bucket_name: str
    sqs_queue_url: str = ""
    tesseract_path: str = "/usr/bin/tesseract"

    cognito_region: str = "eu-central-1"
    cognito_user_pool_id: str = "eu-central-1_t23sf3Gb5"
    cognito_client_id: str = "3pd6tem71q5vf35cbn3rqchhpt"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()