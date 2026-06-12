"""Trivial smoke test that the Celery app imports without errors."""
from app.workers.celery_app import celery_app


def test_celery_app_imports():
    assert celery_app.main == "docuintel"
    assert "app.workers.tasks" in celery_app.conf.include
    assert "app.workers.embedding_tasks" in celery_app.conf.include
