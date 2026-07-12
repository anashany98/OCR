from pathlib import Path
from types import ModuleType

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def test_ocr_runtime_pins_numpy_to_numpy_one_abi():
    requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
    lines = {
        line.strip().lower()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert "numpy==1.26.4" in lines


def test_paddleocr_initialization_runs_inside_process_lock(monkeypatch):
    from app.ocr import paddle

    # A preceding timeout test may intentionally poison the process-level
    # circuit breaker.  This unit tests the successful constructor path, so
    # isolate that mutable process state explicitly.
    monkeypatch.setattr(paddle, "_PROCESS_INIT_FAILED", False)
    monkeypatch.setattr(paddle, "_PROCESS_INIT_FAILED_AT", 0.0)

    events: list[str] = []
    kwargs_seen: list[dict] = []

    class FakePaddleOCR:
        def __init__(self, **kwargs):
            kwargs_seen.append(kwargs)
            events.append(f"init:{kwargs['lang']}")

    class FakeLock:
        def __enter__(self):
            events.append("lock_enter")

        def __exit__(self, exc_type, exc, tb):
            events.append("lock_exit")

    fake_module = ModuleType("paddleocr")
    fake_module.PaddleOCR = FakePaddleOCR
    monkeypatch.setitem(__import__("sys").modules, "paddleocr", fake_module)
    monkeypatch.setattr(paddle, "paddleocr_init_lock", lambda: FakeLock())
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")

    engine = paddle.PaddleOCREngine(lang="en")
    _ = engine._engine

    assert events == ["lock_enter", "init:en", "lock_exit"]
    assert kwargs_seen == [
        {
            "use_textline_orientation": True,
            "lang": "en",
            "enable_mkldnn": False,
            "device": "gpu:1",
        }
    ]


def test_pp_structure_pipeline_initialization_does_not_spawn_daemon_thread(monkeypatch):
    from app.ocr import pp_structure

    class _FakePipeline:
        pass

    def fake_create_pipeline(**kwargs):
        assert kwargs == {"pipeline": "layout_parsing", "device": "gpu", "lang": "es"}
        return _FakePipeline()

    fake_module = ModuleType("paddlex")
    fake_module.create_pipeline = fake_create_pipeline
    monkeypatch.setitem(__import__("sys").modules, "paddlex", fake_module)

    engine = pp_structure.PPStructureEngine(device="gpu")

    assert isinstance(engine._pipeline, _FakePipeline)


def test_successful_reprocess_clears_stale_job_error(monkeypatch, tmp_path):
    from app.database.base import Base
    from app.models import Document, ExtractionJob
    from app.parsers.types import ExtractedDocument, ExtractedPage
    from app.services import document_service

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(document_service.settings, "files_dir", tmp_path)
    monkeypatch.setattr(
        document_service,
        "parse_document",
        lambda *args, **kwargs: ExtractedDocument(pages=[ExtractedPage(page_number=1, text="texto correcto")]),
    )

    with SessionLocal() as db:
        document = Document(
            original_filename="imagen.jpg",
            stored_filename="aa/imagen.jpg",
            source_path="/data/input/imagenes/imagen.jpg",
            file_hash="a" * 64,
            mime_type="image/jpeg",
            extension=".jpg",
            file_size=10,
            document_type="imagen",
            status="pending",
        )
        db.add(document)
        db.flush()
        job = ExtractionJob(
            document_id=document.id,
            job_type="reprocess:full",
            status="pending",
            error_message="error antiguo",
        )
        db.add(job)
        db.commit()

        document_service.process_document(db, document_id=document.id, job_id=job.id)

        db.refresh(job)
        assert job.status == "processed"
        assert job.error_message is None
