"""Smoke tests for the health and readiness probes.

These also serve as the canary that the FastAPI app still imports and wires
up its routers — a failure here usually means a broken import, not a broken
endpoint.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

# Constructed without `with`, so the app's lifespan does not run: these probes
# must answer without database, Redis or model connections.
client = TestClient(app)


@pytest.mark.unit
def test_health_check_reports_healthy() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "ai-banking-api",
        "version": "0.1.0",
    }


@pytest.mark.unit
def test_readiness_check_reports_ready() -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.unit
def test_openapi_schema_builds() -> None:
    """Catches malformed route signatures across every router, not just health."""
    schema = app.openapi()

    assert schema["info"]["title"] == "BETA AID Backend"
    assert "/health" in schema["paths"]
