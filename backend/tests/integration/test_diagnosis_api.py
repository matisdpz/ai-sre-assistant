"""AI diagnosis endpoints against PostgreSQL, with the fake provider (no network)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.ai import AIQuotaError, FakeProvider
from app.config import Settings
from app.main import create_app
from tests.conftest import TEST_INGEST_TOKEN

pytestmark = pytest.mark.integration

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def fake() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(test_database_url: str, clean_db: Engine, fake: FakeProvider) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None, database_url=test_database_url, ingest_token=TEST_INGEST_TOKEN
    )
    with TestClient(create_app(settings, diagnosis_provider=fake)) as test_client:
        yield test_client


def sample(i: int, service: str, **overrides: Any) -> dict[str, Any]:
    values = {
        "service_id": service,
        "ts": (T0 + timedelta(seconds=10 * i)).isoformat(),
        "request_rate": 100.0,
        "error_rate": 1.0,
        "latency_p95_ms": 120.0,
        "cpu_pct": 30.0,
        "mem_pct": 40.0,
        "up": True,
    }
    return values | overrides


def open_incident(client: TestClient) -> str:
    """Healthy baseline, then an error spike on payment-service; other services healthy."""
    samples = []
    for i in range(12):
        breaching = i >= 6
        samples.append(sample(i, "payment-service", error_rate=12.0 if breaching else 1.0))
        samples.append(sample(i, "api-gateway"))
    response = client.post(
        "/api/v1/ingest/metrics",
        json={"samples": samples},
        headers={"Authorization": f"Bearer {TEST_INGEST_TOKEN}"},
    )
    [decision] = response.json()["decisions"]
    return decision["incident_id"]


def test_status_reports_the_provider(client: TestClient) -> None:
    assert client.get("/api/v1/ai/status").json() == {
        "enabled": True,
        "provider": "fake",
        "model": "fake-model",
    }


def test_diagnosis_separates_observed_facts_from_hypotheses(
    client: TestClient, fake: FakeProvider
) -> None:
    incident_id = open_incident(client)
    url = f"/api/v1/incidents/{incident_id}/diagnosis"
    assert client.get(url).status_code == 404  # nothing requested yet: no AI call

    response = client.post(url)

    assert response.status_code == 201
    body = response.json()
    assert body["provider"] == "fake"
    assert any(f.startswith("Average error rate: 1.0 % before") for f in body["facts"])
    assert body["hypotheses"][0]["confidence"] == "low"
    assert "Not a confirmed root cause" in body["disclaimer"]
    assert client.get(url).json()["id"] == body["id"]  # stored, re-read without AI


def test_only_the_incident_and_its_service_metrics_are_sent(
    client: TestClient, fake: FakeProvider
) -> None:
    incident_id = open_incident(client)
    client.post(f"/api/v1/incidents/{incident_id}/diagnosis")

    [context] = fake.contexts
    assert context["incident"]["service_id"] == "payment-service"
    assert len(context["metrics"]) == 12  # payment-service only, not api-gateway's 12
    assert "api-gateway" not in str(context)


def test_provider_error_is_reported_and_nothing_is_stored(
    client: TestClient, fake: FakeProvider
) -> None:
    incident_id = open_incident(client)
    fake.error = AIQuotaError("Gemini quota or rate limit reached. Try again later.")

    response = client.post(f"/api/v1/incidents/{incident_id}/diagnosis")

    assert response.status_code == 429
    assert "quota" in response.json()["detail"]
    assert client.get(f"/api/v1/incidents/{incident_id}/diagnosis").status_code == 404
    # The rest of the application keeps working.
    assert client.get(f"/api/v1/incidents/{incident_id}").status_code == 200


def test_unknown_incident_is_404(client: TestClient, fake: FakeProvider) -> None:
    response = client.post("/api/v1/incidents/00000000-0000-0000-0000-000000000000/diagnosis")
    assert response.status_code == 404
    assert fake.contexts == []
