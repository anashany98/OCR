from app.ai.model_routing import select_chat_model
from app.core.config import settings


def test_fast_model_handles_short_factual_question(monkeypatch):
    monkeypatch.setattr(settings, "ai_model", "primary")
    monkeypatch.setattr(settings, "ai_fast_model", "fast")
    monkeypatch.setattr(settings, "ai_model_routing_enabled", True)

    route = select_chat_model("Cual es el proveedor?")

    assert route.model == "fast"
    assert route.profile == "fast_factual"


def test_primary_model_keeps_synthesis_question(monkeypatch):
    monkeypatch.setattr(settings, "ai_model", "primary")
    monkeypatch.setattr(settings, "ai_fast_model", "fast")

    route = select_chat_model("Compara los presupuestos y explica las diferencias")

    assert route.model == "primary"
    assert route.profile == "primary"


def test_empty_fast_model_preserves_existing_behavior(monkeypatch):
    monkeypatch.setattr(settings, "ai_model", "primary")
    monkeypatch.setattr(settings, "ai_fast_model", "")

    assert select_chat_model("Cual es el proveedor?").model == "primary"
