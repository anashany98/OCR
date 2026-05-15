from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Docu-Intel"
    environment: str = "local"
    api_v1_prefix: str = ""

    database_url: str = "postgresql+psycopg://app:app@postgres:5432/docuintel"
    redis_url: str = "redis://redis:6379/0"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    files_dir: Path = Path("/app/data/files")
    input_dir: Path = Path("/app/data/input")
    scan_interval_seconds: int = 300
    ingestion_stable_seconds: int = 30
    file_storage_strategy: Literal["copy", "hardlink", "auto"] = "auto"
    watcher_enabled: bool = True
    watcher_backend: Literal["native", "polling"] = "native"
    watcher_recursive: bool = True
    watcher_poll_seconds: float = 2.0
    watcher_settle_seconds: float = 5.0
    watcher_rescan_interval_seconds: int = 3600
    watcher_max_files_per_tick: int = 10

    ai_provider: str = "local_openai_compatible"
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: str = ""

    ocr_engine: Literal["paddleocr"] = "paddleocr"
    enable_dots_mocr: bool = False

    embedding_provider: str = "local_hash"
    embedding_base_url: str = ""
    embedding_model: str = "bge-m3"
    embedding_api_key: str = ""
    embedding_dimensions: int = 1024
    embedding_timeout_seconds: float = 10.0
    embedding_fallback_to_hash: bool = True

    integration_clients: str = "external-tool:dev-secret:read,upload"
    integration_enqueue_uploads: bool = True
    integration_rate_limit_per_minute: int = 120
    integration_session_expire_seconds: int = 3600

    jwt_secret: str = "change_me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
    auth_cookie_name: str = "docuintel_token"

    admin_email: str = "admin@local"
    admin_password: str = "admin123"
    admin_name: str = "Administrador"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
