"""Optional live-service checks, enabled only in a GPU-capable environment."""

import os

import httpx
import pytest

_ENDPOINT = os.environ.get("OVISOCR2_INTEGRATION_ENDPOINT", "").rstrip("/")


@pytest.mark.skipif(
    not _ENDPOINT, reason="requires OVISOCR2_INTEGRATION_ENDPOINT and a live GPU service"
)
def test_live_ovisocr2_service_reports_the_pinned_model_revision():
    response = httpx.get(f"{_ENDPOINT}/readyz", timeout=10.0)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["model"] == os.environ.get("OVISOCR2_MODEL", "ATH-MaaS/OvisOCR2")
    assert payload["revision"] == os.environ["OVISOCR2_MODEL_REVISION"]
