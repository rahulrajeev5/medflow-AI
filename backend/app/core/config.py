from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MedFlow AI API"
    database_url: str
    upload_dir: Path = Path("uploads")
    max_upload_mb: int = 10
    cors_origins: str = "http://localhost:5173"
    tesseract_path: str

    aws_profile: str = "medflow"
    aws_region: str = "eu-central-1"
    bedrock_region: str = "eu-central-1"
    s3_bucket_name: str
    sqs_queue_url: str

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )
    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
