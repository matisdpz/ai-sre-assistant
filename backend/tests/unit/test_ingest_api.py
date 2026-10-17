"""Ingest authentication and validation: both are checked before the database is used,
so these tests run against an unreachable database."""

import math
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.detection import RULES
from app.incident_manager import ALLOWED_TRANSITIONS, DETECTION_WINDOW
from app.main import create_app
from app.models import IncidentStatus as S
from app.schemas import MAX_BATCH_SAMPLES, MetricBatchIn, MetricSampleIn

TOKEN = "unit-test-ingest-token"
URL = "/api/v1/ingest/metrics"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _sample(**overrides: Any) -> dict[str, Any]:
    values = {
        "service_id": "payment-service",
        "ts": "2026-01-01T12:00:00Z",
        "request_rate": 100.0,
        "error_rate": 1.0,
        "latency_p95_ms": 120.0,
        "cpu_pct": 30.0,
        "mem_pct": 40.0,
        "up": True,
    }
    values.update(overrides)
    return values


@pytest.fixture
def client() -> TestClient:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:pw@127.0.0.1:1/missing",
        ingest_token=TOKEN,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong-token"}, {"Authorization": f"Basic {TOKEN}"}],
)
def test_missing_or_wrong_token_is_rejected(client: TestClient, headers: dict) -> None:
    response = client.post(URL, json={"samples": [_sample()]}, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_authentication_is_checked_before_the_body(client: TestClient) -> None:
    # An anonymous caller learns nothing about the expected payload.
    response = client.post(URL, json={"garbage": True})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"samples": []},
        {"samples": [_sample(error_rate=101)]},
        {"samples": [_sample(cpu_pct=-1)]},
        {"samples": [_sample(ts="2026-01-01T12:00:00")]},  # naive timestamp
        {"samples": [_sample(region="eu")]},  # unknown field
        {"samples": [_sample(service_id="")]},
    ],
)
def test_invalid_payload_is_rejected(client: TestClient, body: dict) -> None:
    assert client.post(URL, json=body, headers=AUTH).status_code == 422


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_nan_and_infinity_are_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        MetricSampleIn.model_validate(_sample(latency_p95_ms=value))


def test_batch_size_is_limited() -> None:
    with pytest.raises(ValidationError):
        MetricBatchIn.model_validate({"samples": [_sample()] * (MAX_BATCH_SAMPLES + 1)})


def test_detection_window_covers_every_rule() -> None:
    assert all(max(r.breach_samples, r.recovery_samples) <= DETECTION_WINDOW for r in RULES)


def test_status_lifecycle_matches_specification() -> None:
    allowed = {(a, b) for a, targets in ALLOWED_TRANSITIONS.items() for b in targets}
    assert allowed == {(S.OPEN, S.ACKNOWLEDGED), (S.OPEN, S.RESOLVED), (S.ACKNOWLEDGED, S.RESOLVED)}


def test_malformed_incident_id_is_422(client: TestClient) -> None:
    assert client.get("/api/v1/incidents/not-a-uuid").status_code == 422


def test_rules_endpoint_exposes_the_engine_thresholds(client: TestClient) -> None:
    rules = {r["type"]: r for r in client.get("/api/v1/rules").json()}
    assert set(rules) == {r.incident_type.value for r in RULES}
    assert rules["high_error_rate"] == {
        "type": "high_error_rate",
        "label": "error rate",
        "metric": "error_rate",
        "unit": "%",
        "warning": 5.0,
        "critical": 10.0,
        "breach_samples": 3,
        "recovery_samples": 3,
    }
    assert rules["service_down"]["warning"] is None
