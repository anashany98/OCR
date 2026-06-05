from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Docu-Intel"
    environment: Literal["local", "development", "staging", "production"] = "local"
    # Versioned API mount point. All user-facing routers live under this prefix.
    # Integrations API has its own /integrations/v1 prefix (external contract).
    # Set to "" to disable versioning (legacy mode, not recommended).
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://app:app@postgres:5432/docuintel"
    redis_url: str = "redis://redis:6379/0"
    rate_limit_storage_uri: str = ""
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

    # Auto-approve trust shortcut for quality evaluation.
    # A document is marked processed_ok automatically (skipping manual review) if
    # its OCR confidence and classification confidence meet these thresholds, even
    # if some structured fields are missing. Set to 1.0 to disable the shortcut.
    auto_approve_min_ocr: float = 0.90
    auto_approve_min_classification: float = 0.80
    auto_approve_allow_missing_fields: bool = True
    # Quality score below this value triggers processed_low_quality.
    quality_score_threshold: float = 0.55
    # Penalty per quality flag when computing the score.
    quality_flag_penalty: float = 0.04

    ai_provider: str = "local_openai_compatible"
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: str = ""
    # Vision LLM (multimodal). When configured, the agent can ask the
    # vision model to describe image documents (jpg/png/tif/webp) so the
    # main LLM has actual visual content, not just bad OCR. Leave empty
    # to disable vision; the agent will fall back to whatever text /
    # entities are available.
    vision_provider: str = "local_openai_compatible"
    vision_base_url: str = ""
    vision_model: str = ""
    vision_api_key: str = ""
    vision_timeout_seconds: float = 60.0
    vision_max_image_dim: int = 1024  # downscale images before sending to the LLM
    # When enabled, the parser uses the vision model to transcribe tables
    # inside scanned PDFs/photos that PaddleOCR could not structure. This
    # works great with Qwen3-VL-8B-Thinking.
    vision_table_transcription: bool = True
    # How long (in seconds) after the last vision call the vision model
    # stays resident in LM Studio before being unloaded to free VRAM.
    # Set to 0 to unload immediately after each call.
    vision_unload_delay_seconds: int = 300
    # Path to the lms CLI binary inside the container. The Dockerfile /
    # docker-compose mounts the host's lms.exe at this path so the
    # backend can call ``lms load`` / ``lms unload`` to manage the
    # vision model lifecycle on demand.
    lms_cli_path: str = "/usr/local/bin/lms"
    # Master switch for the on-demand vision manager. When false the
    # backend treats vision as always-resident (legacy behaviour).
    vision_on_demand: bool = True
    # Vision model used for structured-output tasks (table extraction,
    # plan room suggestions). Defaults to the same as ``vision_model``
    # but can be overridden to use a non-thinking variant for
    # faster, more deterministic JSON output. The reasoning variant
    # wastes tokens on CoT and often returns empty content.
    vision_model_structured: str = ""

    ocr_engine: Literal["tesseract", "paddleocr", "cascading"] = "cascading"
    enable_dots_mocr: bool = False
    # Tesseract 5 settings (used as primary in the cascade and as the
    # only engine when ocr_engine == "tesseract").
    tesseract_lang: str = "spa+eng"
    tesseract_oem: int = 1   # 1 = LSTM only (Tesseract 5 default, fastest, best quality)
    tesseract_psm: int = 3   # 3 = fully automatic page segmentation
    # Cascade escalation thresholds. The cascade runs Tesseract first
    # and escalates to PaddleOCR when the primary result is "weak" by
    # these metrics. Easy documents (digital PDFs, clean scans) never
    # pay the PaddleOCR init cost.
    ocr_cascading_min_chars: int = 30
    ocr_cascading_min_confidence: float = 0.5
    # Optional Tier 3: PP-Structure (PaddleX layout_parsing). Only fires
    # when Tier 1 AND Tier 2 both fail to produce a usable result. GPU
    # only — the engine refuses to instantiate on CPU because the
    # PaddlePaddle 3.3.x PIR executor crashes layout_parsing on CPU.
    # Off by default; enable per environment.
    ocr_cascading_use_pp_structure: bool = False
    pp_structure_device: str = "gpu"
    pp_structure_lang: str = "es"

    embedding_provider: str = "local_hash"
    embedding_base_url: str = ""
    embedding_model: str = "bge-m3"
    embedding_api_key: str = ""
    embedding_dimensions: int = 1024
    embedding_timeout_seconds: float = 30.0
    embedding_fallback_to_hash: bool = True
    # In-process embedding via sentence-transformers. The model runs on
    # the GPU workers; on CPU-only deployments set device="cpu" and accept
    # the ~10× latency hit. Granite 311M uses asymmetric query/passage
    # prefixes — see LocalSentenceTransformerEmbeddingClient.
    embedding_local_model: str = "ibm-granite/granite-embedding-311m-multilingual-r2"
    embedding_local_device: str = "cuda"
    embedding_local_batch_size: int = 32
    embedding_local_max_length: int = 512
    # In-process reranker via sentence-transformers CrossEncoder. The
    # BGE-reranker-v2-m3 model scores (query, passage) pairs in a single
    # forward pass. Runs on the GPU workers.
    reranker_local_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_local_device: str = "cuda"
    reranker_local_max_length: int = 512

    integration_clients: str = ""
    integration_enqueue_uploads: bool = True
    integration_rate_limit_per_minute: int = 120
    integration_session_expire_seconds: int = 3600
    integration_webhook_url: str = ""
    integration_webhook_secret: str = ""
    integration_webhook_timeout_seconds: float = 5.0
    # Webhook outbox / delivery worker
    webhook_outbox_max_attempts: int = 8
    webhook_outbox_initial_backoff_seconds: int = 30
    webhook_outbox_max_backoff_seconds: int = 3600  # 1 hour
    webhook_outbox_batch_size: int = 25
    webhook_outbox_interval_seconds: int = 30  # how often the worker drains the outbox

    # GlitchTip (Sentry-compatible) error tracking.
    # Leave SENTRY_DSN empty to disable. GlitchTip accepts a Sentry-compatible DSN
    # of the form https://<public_key>@<glitchtip-host>/<project_id>.
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.0  # 0.0 = no performance tracing, 1.0 = everything
    sentry_profiles_sample_rate: float = 0.0
    sentry_environment: str = ""  # defaults to `environment` if empty
    sentry_send_pii: bool = False  # do not send PII by default
    integration_webhook_events: list[str] = Field(
        default_factory=lambda: [
            "document.processed",
            "document.failed",
            "document.needs_review",
            "classification.low_confidence",
            "entity.new_pattern_detected",
            "job.finished",
            "docuintel.webhook_test",
        ]
    )

    jwt_secret: str = "dev_only_jwt_secret_change_me_for_local_development_only"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12
    auth_cookie_name: str = "docuintel_token"
    auth_cookie_secure: bool | None = None
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_login_rate_limit: str = "10/minute"

    max_upload_size_mb: int = 200
    # Max number of file parts in a single multipart upload (python-multipart's
    # default is 1000). Bumped so a folder drag-and-drop or webkitdirectory
    # pick with many files is not rejected before reaching the route.
    max_upload_files: int = 10_000_000
    max_pdf_pages: int = 500
    max_image_megapixels: float = 40.0
    max_excel_rows: int = 100_000
    max_excel_sheets: int = 50
    pdf_ocr_dpi: int = 144
    vector_store: Literal["pgvector", "qdrant"] = "pgvector"

    learning_interval_seconds: int = 300
    # Auto-reject classification_suggestions that stay 'pending' for longer than
    # this. Set to 0 to disable. Runs as a daily Celery Beat task on the
    # maintenance queue.
    learning_stale_pending_days: int = 30
    learning_stale_check_interval_seconds: int = 86_400  # 1 day
    # Soft circuit breaker on the integration proposal tools: warn (and
    # optionally block) clients that submit more than N suggestions per
    # window. Set max to 0 to disable the limit.
    learning_per_client_max_pending: int = 100
    learning_per_client_window_seconds: int = 3_600  # 1 hour

    admin_email: str = "admin@local"
    admin_password: str = "dev_only_admin_password_change_me"
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
        if value in {"change_me", "CHANGE_ME_GENERATE_SECURE_TOKEN_MIN_64_CHARS", "CHANGE_IN_PRODUCTION_USE_64_CHARS_MIN_SECURE"}:
            raise ValueError("JWT_SECRET must be changed from default value for security")
        if environment != "local" and value.startswith("dev_only_"):
            raise ValueError(f"JWT_SECRET must be set explicitly in '{environment}' environment")
        if environment != "local" and len(value) < 64:
            raise ValueError("JWT_SECRET must be at least 64 characters long in non-local environments")
        if environment == "local" and len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters long")
        return value

    @field_validator("admin_password", mode="after")
    @classmethod
    def validate_admin_password(cls, value: str, info: ValidationInfo) -> str:
        environment = info.data.get("environment", "local")
        if value in {"admin123", "CHANGE_ME_MIN_16_CHARS_SECURE_PASSWORD", "CHANGE_IN_PRODUCTION_MIN_16_CHARS"}:
            raise ValueError("ADMIN_PASSWORD must be changed from default value for security")
        if environment != "local" and value.startswith("dev_only_"):
            raise ValueError(f"ADMIN_PASSWORD must be set explicitly in '{environment}' environment")
        if len(value) < 16:
            raise ValueError("ADMIN_PASSWORD must be at least 16 characters long")
        return value

    @field_validator("database_url", mode="after")
    @classmethod
    def validate_db_password(cls, value: str) -> str:
        weak_passwords = {"app", "password", "postgres", "admin", "123456", "changeme", "docuintel"}
        try:
            from urllib.parse import urlparse
            parsed = urlparse(value)
            if parsed.password and parsed.password.lower() in weak_passwords:
                raise ValueError(
                    f"PostgreSQL password is too weak. "
                    f"Generate a secure password with: python -c \"import secrets; print(secrets.token_urlsafe(24))\""
                )
        except ValueError:
            raise
        except Exception:
            pass
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
