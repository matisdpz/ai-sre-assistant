"""Health endpoints without a database: nothing listens on port 1, so connections fail fast."""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

UNREACHABLE_DB = "postgresql+psycopg://user:topsecret@127.0.0.1:1/missing"


def _client() -> TestClient:
    return TestClient(
        create_app(Settings(_env_file=None, database_url=UNREACHABLE_DB, ingest_token="x" * 16))
    )


def test_live_is_ok_even_when_database_is_down() -> None:
    with _client() as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_503_when_database_is_unreachable() -> None:
    with _client() as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"database": "error"}}


def test_ready_failure_does_not_leak_connection_details() -> None:
    with _client() as client:
        body = client.get("/health/ready").text

    for secret in ("topsecret", "127.0.0.1", "missing", "psycopg"):
        assert secret not in body
