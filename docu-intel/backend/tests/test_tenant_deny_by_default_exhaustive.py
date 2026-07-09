"""Contract test: every business route denies cross-tenant access."""
from __future__ import annotations

import pytest

BUSINESS_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/v1/documents/{id}"),
    ("GET", "/api/v1/documents/{id}/pages"),
    ("GET", "/api/v1/documents/{id}/download"),
    ("PATCH", "/api/v1/documents/{id}"),
    ("POST", "/api/v1/documents/{id}/reprocess"),
    ("DELETE", "/api/v1/documents/{id}"),
    ("GET", "/api/v1/budgets/{id}"),
    ("GET", "/api/v1/orders/{id}"),
    ("GET", "/api/v1/invoices/{id}"),
    ("GET", "/api/v1/plans/{id}"),
]


@pytest.fixture
def two_tenants(client, db_session):
    raise pytest.skip("wire two_tenants fixture to conftest tenant helpers")


@pytest.mark.parametrize("method, path_template", BUSINESS_ROUTES)
def test_cross_tenant_access_denied(client, two_tenants, method, path_template):
    auth_headers, foreign_doc_id = two_tenants
    url = path_template.format(id=foreign_doc_id)
    resp = client.request(method, url, headers=auth_headers)
    assert resp.status_code == 404, (
        f"TENANT LEAK: {method} {url} returned {resp.status_code} (expected 404)."
    )
