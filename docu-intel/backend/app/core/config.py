from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Docu-Intel"
    environment: Literal["local", "development", "test", "staging", "production"] = "local"
    # Versioned API mount point. All user-facing routers live under this prefix.
    # Integrations API has its own /integrations/v1 prefix (external contract).
    # Set to "" to disable versioning (legacy mode, not recommended).
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://app:app@postgres:5432/docuintel"
    redis_url: str = "redis://redis:6379/0"
    rate_limit_storage_uri: str = ""
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    # SEC-TENANT-1 (Sprint 1): deny-by-default multi-tenant isolation.
    # When True (the new default), the per-role permissive defaults
    # in ``resolve_user_access_scope`` are skipped: a user with no
    # AccessGroup membership sees zero documents. To grant access
    # in deny-by-default mode, create an AccessGroup with explicit
    # ``hotel_ids`` / ``chain_ids`` and add the user. The migration
    # ``0028_tenant_default_permissive_group`` backfills a
    # "default-permissive" group for every existing non-admin user
    # so deployments upgrading from pre-Sprint-1 do not lose
    # access unexpectedly. Set to ``False`` to restore the legacy
    # permissive role defaults (gestor/operario/auditor see
    # everything by default).
    tenant_access_deny_by_default: bool = True
    # SEC-HEADERS-1 (Sprint 1): Content-Security-Policy mode.
    # ``strict`` = the production profile (no inline scripts, frame-ancestors
    # none, etc.). ``local_dev`` = adds ``ws://localhost:5173`` and
    # ``http://localhost:5173`` to ``connect-src`` so the Vite dev
    # server's HMR keeps working when the operator runs the backend
    # with ENVIRONMENT=local. ``disabled`` = the middleware still
    # emits the non-CSP headers (HSTS, Permissions-Policy, etc.) but
    # omits ``Content-Security-Policy`` entirely (only for debugging).
    # Auto-set to ``local_dev`` when ENVIRONMENT=local; otherwise
    # ``strict``.
    csp_mode: Literal["strict", "local_dev", "disabled"] | None = None
    csp_nonce_enabled: bool = True

    @field_validator("csp_mode", mode="after")
    @classmethod
    def _default_csp_mode(cls, value: str | None, info: ValidationInfo) -> str:
        if value:
            return value
        env = info.data.get("environment", "local")
        return "local_dev" if env == "local" else "strict"

    files_dir: Path = Path("/app/data/files")
    input_dir: Path = Path("/app/data/input")
    scan_interval_seconds: int = 300
    ingestion_stable_seconds: int = 30
    ingestion_max_pending_jobs: int = 200
    # WATCH-1 (Sprint 2): cap on the file size the watcher will
    # try to enqueue. Mirrors ``max_upload_size_mb`` so a file
    # that would be rejected by the HTTP upload endpoint is
    # also rejected by the watcher. Set to 0 to disable (NOT
    # recommended; the worker could OOM on a multi-GB PDF).
    ingestion_max_file_size_mb: int = 500
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
            ".dxf",
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
    auto_approve_min_ocr: float = 0.70
    auto_approve_min_classification: float = 0.65
    auto_approve_allow_missing_fields: bool = True
    # Quality score below this value triggers processed_low_quality.
    quality_score_threshold: float = 0.40
    # Penalty per quality flag when computing the score.
    quality_flag_penalty: float = 0.04

    ai_provider: str = "local_openai_compatible"
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: str = ""
    ai_request_timeout_seconds: float = 120.0
    ai_max_retries: int = 2
    ai_retry_base_delay_seconds: float = 0.25
    ai_circuit_breaker_failures: int = 3
    ai_circuit_breaker_reset_seconds: float = 30.0
    # Max concurrent LLM/vision requests. Prevents VRAM exhaustion
    # when many users ask questions simultaneously. Set to 0 to disable.
    ai_max_concurrent_requests: int = 4
    # M11 (Sprint 4): hard token budget for the context sent to the LLM.
    # The system prompt + user prompt overhead is ~800 tokens; the
    # remainder is context.  Local 8B models typically have 8K context;
    # 32B models 32K.  Default 6000 keeps headroom for the question and
    # the answer.  Set to 0 to disable (no clipping).
    ai_max_context_tokens: int = 6000
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

    ocr_engine: Literal["tesseract", "paddleocr", "pp_structure", "cascading"] = "cascading"
    ocr_engine_warmup_timeout: float = 180.0
    enable_dots_mocr: bool = False
    dots_mocr_endpoint: str = ""
    dots_mocr_model: str = ""
    dots_mocr_api_key: str = ""
    dots_mocr_timeout_seconds: float = 120.0
    dots_mocr_quality_threshold: float = 0.62
    # Domain-specific VLM prompt. "generic" uses standard OCR prompt;
    # "interior_design" uses a specialized prompt for hand-drawn sketches,
    # furniture measurements, fabric samples, and curtain dimensions.
    dots_mocr_domain: str = "interior_design"
    nuextract_enabled: bool = False
    nuextract_base_url: str = "http://nuextract-vllm:8000/v1"
    nuextract_model: str = "numind/NuExtract3"
    nuextract_timeout_seconds: float = 120.0
    nuextract_enable_thinking: bool = False
    nuextract_max_concurrency: int = 1
    nuextract_max_images: int = 4
    nuextract_markdown_temperature: float = 0.2
    nuextract_extraction_temperature: float = 0.2
    nuextract_tier4_enabled: bool = False
    nuextract_hyperextract_enabled: bool = False
    # Tesseract 5 settings (used as primary in the cascade and as the
    # only engine when ocr_engine == "tesseract").
    tesseract_lang: str = "spa+eng"
    tesseract_oem: int = 1  # 1 = LSTM only (Tesseract 5 default, fastest, best quality)
    tesseract_psm: int = 3  # 3 = fully automatic page segmentation
    # Cascade escalation thresholds. The cascade runs Tesseract first
    # and escalates to PaddleOCR when the primary result is "weak" by
    # these metrics. Easy documents (digital PDFs, clean scans) never
    # pay the PaddleOCR init cost.
    ocr_cascading_min_chars: int = 30
    ocr_cascading_min_confidence: float = 0.5
    # O2 — Per-page language detection with adaptive thresholds. When
    # true, the cascade looks up the per-language min_chars /
    # min_confidence from ``THRESHOLDS_BY_LANG`` (German, CJK, etc.)
    # instead of the legacy document-wide constants. Set to False to
    # restore the legacy behaviour of "one threshold for every page".
    ocr_cascading_use_adaptive_thresholds: bool = True
    # O2 — Optional per-page language pack for the OCR engines.
    # When true, the parser detects the dominant language of the
    # page (from the embedded text when present, else inherited
    # from the document-level detection) and tells the engines to
    # load the right language pack (e.g. ``deu`` for German,
    # ``jpn`` for Japanese). Set to False to use the document-wide
    # ``tesseract_lang`` / ``paddle_lang`` for every page.
    ocr_cascading_use_per_page_lang: bool = True
    # S0.6 — Skip the expensive Tier 2 engine when the quality gain is
    # marginal. The cascade already only escalates when the primary
    # result is "unacceptable" (below min_chars / min_confidence), but
    # the fallback can still be only marginally better. When this flag
    # is true, the cascade keeps the primary result unless the
    # fallback beats it by at least
    # ``ocr_cascading_skip_quality_improvement`` on the combined quality
    # score (or contributes >= ``ocr_cascading_skip_alnum_gain`` more
    # alphanumeric characters). Set to False to restore the legacy
    # behaviour of "any quality improvement wins".
    ocr_cascading_skip_if_no_significant_gain: bool = True
    # Minimum quality-score improvement (delta on the cascade's
    # 0..1 combined score) the fallback must show over the primary
    # to be considered a "significant" win. Below this delta the
    # primary is kept and the fallback's result is discarded.
    ocr_cascading_skip_quality_improvement: float = 0.10
    # Minimum absolute gain in alphanumeric characters the fallback
    # must show over the primary to be considered a "significant" win
    # even when the quality delta is small. Useful for noisy Tier 1
    # outputs that happen to score high on density (lots of digits /
    # letters, all wrong).
    ocr_cascading_skip_alnum_gain: int = 30
    # Optional Tier 3: PP-Structure (PaddleX layout_parsing). Only fires
    # when Tier 1 AND Tier 2 both fail to produce a usable result. GPU
    # only — the engine refuses to instantiate on CPU because the
    # PaddlePaddle 3.3.x PIR executor crashes layout_parsing on CPU.
    # Off by default; enable per environment.
    ocr_cascading_use_pp_structure: bool = False
    pp_structure_device: str = "gpu"
    pp_structure_lang: str = "es"
    paddle_lang: str = "es"
    # Number of scanned pages to OCR in parallel within a single document.
    # Each worker thread opens its own fitz handle and runs the cascade
    # independently; the OCR C extensions release the GIL so this achieves
    # real parallelism. Bounded to keep VRAM in check (each concurrent
    # Paddle/PP-Structure instance holds model weights). Set to 1 to
    # disable parallelism (serial behaviour, same as before).
    ocr_page_parallelism: int = 2

    # Default to the OpenAI-compatible path so a fresh deployment that
    # forgets to set EMBEDDING_PROVIDER still tries to use a real model.
    # Operators that want a pure-offline, no-server mode can set
    # ``local_hash`` explicitly. Hash fallback is NOT supported — the
    # policy is to fail fast if the embedding provider is unreachable.
    embedding_provider: str = "local_openai_compatible"
    embedding_base_url: str = ""
    # F2-01: pinned to Granite multilingual R2 (768d, cosine).
    # Do NOT change without a full re-embed migration.
    embedding_model: str = "ibm-granite/granite-embedding-311m-multilingual-r2"
    embedding_api_key: str = ""
    # Cambiar este valor requiere migración manual:
    # ALTER COLUMN embedding TYPE VECTOR(<nueva_dim>) + rebuild del índice.
    embedding_dimensions: int = 768
    embedding_allow_dimension_coercion: bool = False
    embedding_timeout_seconds: float = 30.0
    embedding_query_instruction: str | None = None
    embedding_passage_instruction: str | None = None
    # E2 — BM25 (PostgreSQL full-text) hybrid-search knobs. When
    # ``search_use_bm25`` is true (default) ``search_hybrid`` runs
    # the BM25 branch alongside the cosine and ILIKE branches and
    # fuses the three via RRF. The per-strategy weights are
    # overridden automatically when ``search_bm25_adaptive_weights``
    # is true and the query matches a code-like or
    # natural-language shape.
    search_use_bm25: bool = True
    search_bm25_adaptive_weights: bool = True
    # RRF k constant. Larger k reduces the contribution of any
    # single branch's top-1 hit; smaller k makes the top hit
    # dominate. 60 is the standard value from the RRF paper.
    search_rrf_k: int = 60
    # R1 — Query transformer knobs. The retriever can expand a
    # terse or ambiguous user query into a list of retrieval-
    # friendly variants via the local LLM (HyDE for natural-
    # language questions, multi-query for terse / code-like
    # questions). The transformer is fail-safe: when the LLM is
    # unavailable the original query is returned unchanged.
    search_use_query_transformer: bool = True
    search_query_transform_strategy: str = "auto"  # hyde | multi_query | auto | off
    search_query_transform_max_queries: int = 3
    # E5 — Maximal Marginal Relevance knobs. When enabled, the
    # reranker is followed by an MMR pass that re-orders the
    # top-k to reduce near-duplicates. ``lambda`` controls the
    # relevance / diversity trade-off (1.0 = pure relevance,
    # 0.0 = pure diversity); 0.7 is the standard sweet spot.
    search_use_mmr: bool = True
    search_mmr_lambda: float = 0.7
    # MMR operates on a small pool. The default ``max(limit*3, 15)``
    # gives MMR enough candidates to pick from while keeping the
    # n-gram similarity matrix cheap. Override only when the
    # operator needs to push diversity harder.
    search_mmr_pool_size: int = 0  # 0 = use the default
    # Multi-query expansion: generate N query variations to improve
    # recall when the user's phrasing differs from the document's.
    search_multi_query_enabled: bool = True
    search_multi_query_max_variants: int = 3
    # R2 — Prompt-injection defence knobs. ``sensitivity``
    # controls how aggressive the regex detector is
    # (``low`` catches only obvious patterns, ``high`` is very
    # aggressive and will flag some legit Spanish text). ``action``
    # controls what we do with a flagged chunk: ``sanitize``
    # redacts the matched text, ``drop`` returns an empty
    # excerpt, ``log`` is the no-op that just records the
    # attempt. Default = ``sanitize`` + ``medium``.
    prompt_injection_sensitivity: str = "medium"  # low | medium | high
    prompt_injection_action: str = "sanitize"  # log | sanitize | drop
    # When true, the RAG prompt wraps every chunk in
    # ``<chunk>...</chunk>`` XML tags with an explicit
    # "treat-as-data" instruction. The system prompt also
    # reinforces the structural separation. Disable only when
    # the LLM is known to handle the wrapping poorly.
    prompt_injection_use_xml_wrap: bool = True
    # R3 — Feedback loop knobs. ``positive_weight`` and
    # ``negative_weight`` are the per-vote deltas applied to a
    # chunk's ``weight`` column (the value is interpolated
    # towards 1.0 so a single vote cannot dominate). The
    # ``min_votes_to_apply`` gate prevents a single user from
    # swaying the retriever; the loop only adjusts the weight
    # once at least N distinct votes are on the table. The
    # ``rebalance_window_days`` knob controls the periodic
    # decay (a weight of 1.5 drops to 1.25 after 30 days, etc.).
    feedback_positive_weight: float = 0.20
    feedback_negative_weight: float = -0.30
    feedback_min_votes_to_apply: int = 3
    feedback_rebalance_window_days: int = 30
    feedback_rebalance_decay_per_day: float = 0.05
    # E3 — Safety / observability knobs for the new filter set.
    # ``search_filter_max_date_range_days`` does NOT truncate the
    # query (the operator is allowed to ask for any range) but
    # logs a warning when the range is suspiciously wide so a
    # missing ``created_to`` (defaulting to "epoch") is not
    # silently shipped to production.
    search_filter_max_date_range_days: int = 365 * 5
    # Default OCR confidence floor used by the admin UI when the
    # operator does not pin one explicitly. Tied to
    # ``processed_low_quality`` so a single number governs both
    # ends.
    search_min_ocr_confidence_default: float = 0.50
    # E1 — Structure-aware chunking knobs. The legacy defaults
    # (220 words, 40 overlap) match the previous implementation;
    # the structure-aware flags are opt-in so a deployment that
    # pins a behaviour can keep the old chunker.
    embedding_chunk_max_words: int = 220
    embedding_chunk_overlap_words: int = 40
    embedding_chunk_respect_tables: bool = True
    embedding_chunk_respect_headings: bool = True
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
    # AUTH-JWT-1 (Sprint 1): per-purpose secrets so a leak in one
    # surface (e.g. an integration API key) cannot be used to forge
    # another surface (e.g. a user access token). Empty values
    # fall back to ``jwt_secret`` at the use site for backward
    # compatibility; production deployments MUST set distinct
    # values. Generate each with
    # ``python -c "import secrets; print(secrets.token_urlsafe(64))"``.
    integration_jwt_secret: str = ""
    api_key_hmac_secret: str = ""
    auth_cookie_secure: bool | None = None
    auth_cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    auth_login_rate_limit: str = "10/minute"

    max_upload_size_mb: int = 500  # Bumped for large architectural plans (up to 300 MB)
    # Max number of file parts in a single multipart upload (python-multipart's
    # default is 1000). 2000 keeps per-request memory bounded while still
    # allowing a folder drag-and-drop of a few hundred files. Raise only if
    # you really need to upload thousands of files in a single request.
    max_upload_files: int = 2000
    max_pdf_pages: int = 1000  # Bumped for large plan sets
    max_image_megapixels: float = 40.0
    max_excel_rows: int = 100_000
    max_excel_sheets: int = 50
    pdf_ocr_dpi: int = 300
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

    # A7 - Automatic re-embed / re-OCR loop. Picks documents that still
    # have chunks with ``needs_reembedding=True`` (embeddings failed
    # during the original processing) or whose OCR confidence fell below
    # ``reembed_low_confidence_threshold`` (likely the OCR engine or
    # pre-processing has improved since), and re-runs the cheap embedding
    # step or the full pipeline respectively.
    #
    # Set ``reembed_enabled=False`` to disable the beat schedule without
    # removing the task from the include list.
    reembed_enabled: bool = True
    reembed_interval_seconds: int = 900  # 15 min
    reembed_batch_size: int = 5
    reembed_low_confidence_threshold: float = 0.60

    # Centralised OCR-confidence threshold. Lowered from 0.70 to 0.60
    # per user request: real-world scans with 60-69% confidence still
    # carry recoverable text and were being silently dropped from
    # the LLM context under the old threshold. This single value is
    # the canonical source for every consumer (quality scoring, work
    # inbox, OCR review, re-embed beat, plan needs_review trigger).
    low_ocr_confidence_threshold: float = 0.60

    # P2 — Plan symbol detection (YOLO). The default model is the
    # ``SamirShabani/Architect`` YOLOv8m fine-tuned on FloorPlanCAD
    # (CC BY-NC 4.0). Operators can point ``plan_symbols_model_path`` to
    # a local ``.pt`` file (e.g. a custom-trained model on their own
    # floor plans) without changing the code.
    #
    # Set ``plan_symbols_enabled=False`` to keep the pipeline calls in
    # place but skip inference (useful when the model is missing and
    # you want to keep the rest of the pipeline fast).
    plan_symbols_enabled: bool = True
    plan_symbols_model_path: str = "SamirShabani/Architect"
    plan_symbols_confidence_threshold: float = 0.35
    plan_symbols_iou_threshold: float = 0.45
    plan_symbols_image_size: int = 640
    plan_symbols_device: str = "cpu"  # "cpu" or "cuda"
    # When a document qualifies for re-OCR (low confidence) we don't want
    # to spam the heavy queue with 500 docs at once, so we cap the heavy
    # re-OCR portion of a single tick to this number. Re-embed-only
    # documents are still capped by ``reembed_batch_size``.
    reembed_reocr_per_tick: int = 1
    # Current version label of the OCR engine. Stored on every
    # ``DocumentPage.ocr_engine_version`` so the periodic re-OCR sweep
    # can find pages produced with a stale version and re-process them
    # automatically. Bump this when you upgrade PaddleOCR / Tesseract /
    # pp-structure and the next ``reprocess_with_new_ocr_engine_task``
    # tick will pick them up.
    current_ocr_engine_version: str = "paddleocr-v3-adaptive-v1"
    # Cap the number of re-OCR jobs enqueued per tick by the engine
    # version sweep. Mirrors ``reembed_reocr_per_tick`` to keep the
    # heavy queue from being flooded.
    reocr_versioned_per_tick: int = 50
    # Master switch for the periodic engine-version sweep. Disabled by
    # default so deployments that have not migrated pick up no extra
    # work; set ``OCR_REPROCESS_ON_VERSION_DRIFT=true`` to enable.
    ocr_reprocess_on_version_drift: bool = True

    # =========================================================================
    # Hyper-Extract — optional structured-extraction layer on top of OCR
    # =========================================================================
    # When ``hyperextract_enabled`` is False the entire module is bypassed
    # (no provider call, no DB write, no extra latency). When True, the
    # service is invoked *after* the OCR has produced clean text and the
    # result is persisted in ``document_extractions``. Failure is contained
    # so a Hyper-Extract outage never breaks the OCR pipeline.
    hyperextract_enabled: bool = False
    hyperextract_provider: str = "openai_compatible"
    hyperextract_base_url: str = ""
    hyperextract_model: str = ""
    hyperextract_api_key: str = ""
    hyperextract_timeout_seconds: float = 120.0
    hyperextract_max_retries: int = 1
    hyperextract_output_dir: str = "./storage/hyperextract"
    # Default document_type to assume when the classifier is unsure or
    # when the operator triggers an extract with no type. One of:
    # ``factura``, ``albaran``, ``contrato``, ``presupuesto``.
    hyperextract_default_type: str = "factura"
    # Whether to persist the raw provider payload (audit / debugging).
    hyperextract_persist_raw_output: bool = True
    # When True, also call Hyper-Extract automatically as part of the
    # standard ``process_document`` pipeline. When False, only explicit
    # calls via the API or the test script trigger an extraction.
    hyperextract_run_in_pipeline: bool = False

    metrics_token: str = ""
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
        # ``test`` and ``development`` are treated like ``local`` for
        # the dev-only prefix / length rules so the CI integration
        # suite (which sets ``ENVIRONMENT=test`` and inherits the
        # dev defaults) can boot without bespoke secret generation.
        # ``staging`` and ``production`` still get the strict checks.
        environment = info.data.get("environment", "local")
        is_dev_like = environment in {"local", "development", "test"}
        if value in {
            "change_me",
            "CHANGE_ME_GENERATE_SECURE_TOKEN_MIN_64_CHARS",
            "CHANGE_IN_PRODUCTION_USE_64_CHARS_MIN_SECURE",
        }:
            raise ValueError("JWT_SECRET must be changed from default value for security")
        if not is_dev_like and value.startswith("dev_only_"):
            raise ValueError(f"JWT_SECRET must be set explicitly in '{environment}' environment")
        if not is_dev_like and len(value) < 64:
            raise ValueError(
                "JWT_SECRET must be at least 64 characters long in non-local environments"
            )
        if is_dev_like and len(value) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters long")
        return value

    @field_validator("admin_password", mode="after")
    @classmethod
    def validate_admin_password(cls, value: str, info: ValidationInfo) -> str:
        # See ``validate_jwt_secret`` for the rationale: dev-like
        # environments (``local`` / ``development`` / ``test``) keep
        # the ``dev_only_*`` admin default so the test fixtures and
        # ``docker compose up`` can boot out of the box.
        environment = info.data.get("environment", "local")
        is_dev_like = environment in {"local", "development", "test"}
        if value in {
            "admin123",
            "CHANGE_ME_MIN_16_CHARS_SECURE_PASSWORD",
            "CHANGE_IN_PRODUCTION_MIN_16_CHARS",
        }:
            raise ValueError("ADMIN_PASSWORD must be changed from default value for security")
        if not is_dev_like and value.startswith("dev_only_"):
            raise ValueError(
                f"ADMIN_PASSWORD must be set explicitly in '{environment}' environment"
            )
        if len(value) < 16:
            raise ValueError("ADMIN_PASSWORD must be at least 16 characters long")
        return value

    @field_validator("database_url", mode="after")
    @classmethod
    def validate_db_password(cls, value: str, info: ValidationInfo) -> str:
        # The CI integration test job spins up a throwaway pgvector
        # container with the ``app:app`` user the pgvector image ships
        # with by default. We must not refuse to boot in that
        # environment just because the password is in the well-known
        # weak set, otherwise ``alembic upgrade head`` cannot even
        # construct :data:`Settings` and the test job fails at
        # settings import rather than at the actual schema upgrade.
        # ``development`` and ``local`` are explicitly skipped so that
        # ``docker compose up`` against a throwaway stack still boots.
        # Production and ``staging`` environments still get the strict
        # check via :meth:`_validate_production_hardening`.
        environment = info.data.get("environment", "local")
        if environment in {"local", "development", "test"}:
            return value
        weak_passwords = {"app", "password", "postgres", "admin", "123456", "changeme", "docuintel"}
        try:
            from urllib.parse import urlparse

            parsed = urlparse(value)
            if parsed.password and parsed.password.lower() in weak_passwords:
                raise ValueError(
                    "PostgreSQL password is too weak. "
                    'Generate a secure password with: python -c "import secrets; print(secrets.token_urlsafe(24))"'
                )
        except ValueError:
            raise
        except Exception:
            pass
        return value

    @field_validator("cors_origins", mode="after")
    @classmethod
    def _validate_production_hardening(cls, value: list[str], info: ValidationInfo) -> list[str]:
        """Cross-setting guards for non-local environments.

        These run after every other field is validated; we read the
        already-validated ``environment`` value from ``info.data``. The
        goal is to fail-fast at startup if a production deployment
        shipped with a permissive default that would let an attacker
        spoof source IPs (uvicorn) or send cross-site credentials
        (CORS).
        """
        environment = info.data.get("environment", "local")
        if environment == "local":
            return value
        # The frontend's VITE_API_BASE_URL is the only proxy we expect in
        # production; a wildcard CORS in production defeats the cookie
        # SameSite policy and is a release blocker. CORS_ORIGINS was
        # already validated above; this is a defensive second check.
        if "*" in value:
            raise ValueError("CORS_ORIGINS must not contain '*' in non-local environments")
        return value

    @field_validator("embedding_allow_dimension_coercion", mode="after")
    @classmethod
    def _warn_coercion(cls, value: bool) -> bool:
        if value:
            import warnings
            warnings.warn(
                "EMBEDDING_ALLOW_DIMENSION_COERCION activo: vectores pueden "
                "corromperse. Solo para migración.",
                stacklevel=2,
            )
        return value

    @field_validator("metrics_token", mode="after")
    @classmethod
    def _require_metrics_token_nonlocal(cls, value: str, info: ValidationInfo) -> str:
        environment = info.data.get("environment", "local")
        if environment in {"local", "development", "test"}:
            return value
        if not value:
            raise ValueError(
                f"METRICS_TOKEN must be set explicitly in '{environment}' environment"
            )
        return value

    @field_validator("embedding_model", mode="after")
    @classmethod
    def _validate_embedding_profile(cls, value: str, info: ValidationInfo) -> str:
        """F2-01: validate model/dimension combination at startup."""
        dims = info.data.get("embedding_dimensions", 768)
        # Known valid profiles — extend when adding new models.
        VALID_PROFILES = {
            "ibm-granite/granite-embedding-311m-multilingual-r2": 768,
            "BAAI/bge-m3": 1024,
        }
        expected = VALID_PROFILES.get(value)
        if expected is not None and dims != expected:
            raise ValueError(
                f"EMBEDDING_MODEL '{value}' expects {expected} dimensions, "
                f"but EMBEDDING_DIMENSIONS is {dims}. Fix the mismatch."
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
