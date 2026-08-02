from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MedFlow AI API"
    database_url: str = "postgresql+psycopg://medflow:medflow@localhost:5432/medflow"
    upload_dir: Path = Path("uploads")
    max_upload_mb: int = 10
    cors_origins: str = "http://localhost:5173"
    tesseract_path: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
