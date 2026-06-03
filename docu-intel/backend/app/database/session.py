from collections.abc import Generator
from threading import Lock

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings


_engine: Engine | None = None
_engine_url: str | None = None
_session_factory = None
_engine_lock = Lock()


def _build_engine(database_url: str) -> Engine:
    engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in database_url:
            engine_kwargs["poolclass"] = StaticPool
    else:
        engine_kwargs["pool_size"] = 20
        engine_kwargs["pool_recycle"] = 3600
    return create_engine(database_url, **engine_kwargs)


def create_app_engine(database_url: str) -> Engine:
    return _build_engine(database_url)


def get_engine() -> Engine:
    global _engine, _engine_url, _session_factory

    database_url = settings.database_url
    if _engine is None or _engine_url != database_url:
        with _engine_lock:
            if _engine is None or _engine_url != database_url:
                _engine = _build_engine(database_url)
                _engine_url = database_url
                _session_factory = sessionmaker(bind=_engine, autocommit=False, autoflush=False, expire_on_commit=False)
    assert _engine is not None
    return _engine


def get_session_factory():
    get_engine()
    assert _session_factory is not None
    return _session_factory


class _SessionFactoryProxy:
    def __call__(self):
        return get_session_factory()()

    def __getattr__(self, name: str):
        return getattr(get_session_factory(), name)


SessionLocal = _SessionFactoryProxy()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

