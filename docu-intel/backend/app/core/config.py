from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Docu-Intel"
    environment: Literal["local", "development", "staging", "production"] = "local"
    api_v1_prefix: str = ""

    database_url: str = "postgresql+psycopg://app:app@postgres:5432/docuintel"
    redis_url: str = "redis://redis:6379/0"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    files_dir: Path = Path("/app/data/files")
    input_dir: Path = Path("/app/data/input")
    scan_interval_seconds: int = 300
    ingestion_stable_seconds: int = 30
    ingestion_max_pending_jobs: int = 200
    allowed_file_extensions: list[str] = Field(
        default_factory=lambda: [
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".tif",
            ".tiff",
            ".bmp",
            ".webp",
            ".xls",
            ".xlsx",
            ".xlsm",
            ".csv",
            ".tsv",
            ".txt",
            ".log",
            ".eml",
            ".doc",
            ".docx",
        ]
    )
    file_storage_strategy: Literal["copy", "hardlink", "auto"] = "auto"
    watcher_enabled: bool = True
    watcher_backend: Literal["native", "polling"] = "native"
    watcher_recursive: bool = True
    watcher_poll_seconds: float = 5.0
    watcher_settle_seconds: float = 10.0
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
    embedding_timeout_seconds: float = 30.0
    embedding_fallback_to_hash: bool = True

    integration_clients: str = ""
    integration_enqueue_uploads: bool = True
    integration_rate_limit_per_minute: int = 120
    integration_session_expire_seconds: int = 3600
    integration_webhook_url: str = ""
    integration_webhook_secret: str = ""
    integration_webhook_events: list[str] = Field(
        default_factory=lambda: [
            "document.processed",
            "document.failed",
            "document.needs_review",
            "job.finished",
            "docuintel.webhook_test",
        ]
    )

    jwt_secret: str = "dev_only_change_this_jwt_secret_before_deployment_64_chars"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
    auth_cookie_name: str = "docuintel_token"

    admin_email: str = "admin@local"
    admin_password: str = "dev_only_change_this_admin_password"
    admin_name: str = "Administrador"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("allowed_file_extensions", mode="before")
    @classmethod
    def split_allowed_file_extensions(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip().lower() for item in value.split(",") if item.strip()]
        return [str(item).strip().lower() for item in value]

    @field_validator("integration_webhook_events", mode="before")
    @classmethod
    def split_integration_webhook_events(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [str(item).strip() for item in value]

    @field_validator("jwt_secret", mode="after")
    @classmethod
    def validate_jwt_secret(cls, value: str, info: ValidationInfo) -> str:
        environment = info.data.get("environment", "local")
        if value in {"change_me", "CHANGE_ME_GENERATE_SECURE_TOKEN_MIN_64_CHARS"}:
            raise ValueError("JWT_SECRET must be changed from default value for security")
        if environment == "production" and value.startswith("dev_only_"):
            raise ValueError("JWT_SECRET must be set explicitly in production")
        if len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters long")
        return value

    @field_validator("admin_password", mode="after")
    @classmethod
    def validate_admin_password(cls, value: str, info: ValidationInfo) -> str:
        environment = info.data.get("environment", "local")
        if value in {"admin123", "CHANGE_ME_MIN_16_CHARS_SECURE_PASSWORD"}:
            raise ValueError("ADMIN_PASSWORD must be changed from default value for security")
        if environment == "production" and value.startswith("dev_only_"):
            raise ValueError("ADMIN_PASSWORD must be set explicitly in production")
        if len(value) < 16:
            raise ValueError("ADMIN_PASSWORD must be at least 16 characters long")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
