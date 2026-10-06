"""Health and CORS. These routes do not open a database connection."""

from __future__ import annotations

from fastapi.testclient import TestClient

from data_api.app import create_app


def test_health() -> None:
    response = TestClient(create_app()).get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "service": "beta-aid-data-api"}


def test_cors_allows_the_default_console_origin(monkeypatch) -> None:
    monkeypatch.delenv("DATA_API_CORS_ORIGINS", raising=False)
    client = TestClient(create_app())
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_an_unlisted_origin(monkeypatch) -> None:
    monkeypatch.delenv("DATA_API_CORS_ORIGINS", raising=False)
    client = TestClient(create_app())
    response = client.get("/health", headers={"Origin": "https://example.com"})
    assert response.headers.get("access-control-allow-origin") is None


def test_cors_origins_come_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("DATA_API_CORS_ORIGINS", "http://localhost:5173, http://localhost:3000")
    client = TestClient(create_app())
    allowed = client.get("/health", headers={"Origin": "http://localhost:5173"})
    also = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert also.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_preflight_allows_get(monkeypatch) -> None:
    monkeypatch.delenv("DATA_API_CORS_ORIGINS", raising=False)
    response = TestClient(create_app()).options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "GET" in response.headers["access-control-allow-methods"]
