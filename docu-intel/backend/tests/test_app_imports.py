def test_fastapi_app_imports_all_routes(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    from app.core.config import settings

    settings.database_url = "sqlite+pysqlite:///:memory:"

    from app.main import app

    assert app.title == "Docu-Intel"
    assert any(middleware.cls.__name__ == "PerformanceMonitorMiddleware" for middleware in app.user_middleware)
