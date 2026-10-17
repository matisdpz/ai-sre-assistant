"""AI provider and diagnosis facts. No real API call: Gemini is replaced by MockTransport."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.ai import (
    AIInvalidResponseError,
    AIQuotaError,
    AITimeoutError,
    AIUnavailableError,
    GeminiProvider,
)
from app.config import Settings
from app.diagnosis import MAX_CONTEXT_POINTS, build_context, compute_facts
from app.main import build_provider, create_app
from app.models import (
    EventKind,
    Incident,
    IncidentEvent,
    IncidentStatus,
    IncidentType,
    MetricSnapshot,
    Severity,
)

KEY = "AIza-test-key-not-real"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
VALID_ANSWER = {
    "summary": "Error spike on payment-service.",
    "hypotheses": [
        {
            "title": "Dependency failure",
            "reasoning": "Latency and errors rose together.",
            "confidence": "medium",
            "supporting_facts": ["Average p95 latency rose."],
        }
    ],
    "suggested_checks": ["Check the database service metrics."],
}


def gemini_reply(answer: Any) -> dict[str, Any]:
    text = answer if isinstance(answer, str) else json.dumps(answer)
    return {
        "candidates": [
            {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}
        ]
    }


def provider_with(reply: Any) -> tuple[GeminiProvider, list[httpx2.Request]]:
    """`reply` is an httpx2.Response, an exception to raise, or a JSON body (200)."""
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx2.Response):
            return reply
        return httpx2.Response(200, json=reply)

    return GeminiProvider(KEY, "gemini-test", transport=httpx2.MockTransport(handler)), requests


CONTEXT = {"incident": {"type": "high_error_rate", "service_id": "payment-service"}, "facts": []}


# --- Gemini provider ------------------------------------------------------------------


def test_request_shape_and_valid_answer() -> None:
    provider, requests = provider_with(gemini_reply(VALID_ANSWER))

    result = provider.diagnose(CONTEXT)

    assert result.hypotheses[0].confidence == "medium"
    [request] = requests
    assert request.url.path == "/v1beta/models/gemini-test:generateContent"
    assert request.headers["x-goog-api-key"] == KEY
    assert "key" not in request.url.params  # never in the URL (logs)
    body = json.loads(request.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert (
        "Never present a hypothesis as a confirmed root cause"
        in (body["systemInstruction"]["parts"][0]["text"])
    )
    assert json.loads(body["contents"][0]["parts"][0]["text"]) == CONTEXT


@pytest.mark.parametrize(
    ("reply", "error", "message"),
    [
        (httpx2.Response(429, text="RESOURCE_EXHAUSTED"), AIQuotaError, "quota"),
        (httpx2.Response(401, text="bad key"), AIUnavailableError, "rejected the API key"),
        (httpx2.Response(403, text="denied"), AIUnavailableError, "rejected the API key"),
        (httpx2.Response(400, text="bad model"), AIUnavailableError, "GEMINI_MODEL"),
        (httpx2.Response(503, text="overloaded"), AIUnavailableError, "HTTP 503"),
        (httpx2.ReadTimeout("slow"), AITimeoutError, "in time"),
        (httpx2.ConnectError("dns"), AIUnavailableError, "unreachable"),
        (gemini_reply("not json"), AIInvalidResponseError, "could not be used"),
        (gemini_reply({**VALID_ANSWER, "hypotheses": []}), AIInvalidResponseError, "could not"),
        (
            gemini_reply(
                {
                    **VALID_ANSWER,
                    "hypotheses": [{**VALID_ANSWER["hypotheses"][0], "confidence": "certain"}],
                }
            ),
            AIInvalidResponseError,
            "could not",
        ),
        ({"promptFeedback": {"blockReason": "SAFETY"}}, AIInvalidResponseError, "SAFETY"),
    ],
)
def test_provider_failures_become_clear_errors(reply: Any, error: type, message: str) -> None:
    provider, _ = provider_with(reply)

    with pytest.raises(error, match=message) as caught:
        provider.diagnose(CONTEXT)

    assert KEY not in caught.value.message
    assert "RESOURCE_EXHAUSTED" not in caught.value.message  # raw provider text stays in logs


# --- configuration --------------------------------------------------------------------


def _settings(**overrides: Any) -> Settings:
    values = {
        "_env_file": None,
        "database_url": "postgresql+psycopg://u:p@127.0.0.1:1/missing",
        "ingest_token": "x" * 16,
    }
    return Settings(**(values | overrides))


@pytest.mark.parametrize("key", [None, "", "   "])
def test_no_key_means_ai_disabled(key: str | None) -> None:
    assert build_provider(_settings(gemini_api_key=key)) is None


def test_key_enables_gemini_with_the_configured_model() -> None:
    provider = build_provider(_settings(gemini_api_key=KEY, gemini_model="gemini-x"))
    assert provider is not None
    assert (provider.name, provider.model) == ("gemini", "gemini-x")
    assert KEY not in repr(_settings(gemini_api_key=KEY))


def test_disabled_ai_is_reported_and_diagnosis_is_503() -> None:
    with TestClient(create_app(_settings())) as client:
        assert client.get("/api/v1/ai/status").json() == {
            "enabled": False,
            "provider": None,
            "model": None,
        }
        response = client.post(f"/api/v1/incidents/{uuid.uuid4()}/diagnosis")
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


# --- observed facts (pure) ------------------------------------------------------------


def snapshot(i: int, **overrides: Any) -> MetricSnapshot:
    values = {
        "service_id": "payment-service",
        "ts": T0 + timedelta(seconds=10 * i),
        "request_rate": 80.0,
        "error_rate": 1.0,
        "latency_p95_ms": 180.0,
        "cpu_pct": 40.0,
        "mem_pct": 55.0,
        "up": True,
    }
    return MetricSnapshot(**(values | overrides))


def incident(**overrides: Any) -> Incident:
    values = {
        "id": uuid.uuid4(),
        "service_id": "payment-service",
        "type": IncidentType.HIGH_ERROR_RATE,
        "severity": Severity.CRITICAL,
        "status": IncidentStatus.OPEN,
        "summary": "error rate >= 10 %",
        "threshold": 10.0,
        "peak_value": 15.4,
        "started_at": T0 + timedelta(seconds=100),
        "detected_at": T0 + timedelta(seconds=120),
        "recovered_at": T0 + timedelta(seconds=180),
        "evidence": [],
    }
    item = Incident(**(values | overrides))
    item.events = [IncidentEvent(kind=EventKind.DETECTED)]
    return item


def degraded_samples() -> list[MetricSnapshot]:
    before = [snapshot(i) for i in range(10)]
    during = [snapshot(i, error_rate=15.0, latency_p95_ms=1300.0) for i in range(10, 18)]
    after = [snapshot(i) for i in range(18, 22)]
    return before + during + after


def test_facts_compare_metrics_before_and_during() -> None:
    facts = compute_facts(incident(), degraded_samples())

    assert facts[0].startswith(
        "Incident type high_error_rate (error rate) on payment-service (simulated telemetry)"
    )
    assert "Peak error rate: 15.4 % (threshold for critical: 10 %)." in facts
    assert "Metrics recovered after 80 s." in facts
    assert any(f.startswith("Average p95 latency: 180.0 ms before") for f in facts)
    assert any(f.startswith("Average error rate: 1.0 % before") for f in facts)
    assert not any("CPU" in f or "memory" in f for f in facts)  # unchanged: not reported


def test_facts_report_downtime_retriggers_and_missing_baseline() -> None:
    item = incident(type=IncidentType.SERVICE_DOWN, recovered_at=None)
    item.events = [IncidentEvent(kind=k) for k in ("detected", "recovered", "retriggered")]
    samples = [snapshot(i, up=False) for i in range(10, 14)]

    facts = compute_facts(item, samples)

    assert "Metrics recovered and breached again 1 time(s)." in facts
    assert "The service reported down in 4 of 4 samples during it." in facts
    assert any("no baseline" in f for f in facts)
    assert not any(f.startswith("Peak") for f in facts)  # meaningless for service_down


def test_context_contains_only_this_incident_and_is_downsampled() -> None:
    samples = [snapshot(i) for i in range(500)]
    context = build_context(incident(), ["a fact"], samples)

    assert context["incident"]["service_id"] == "payment-service"
    assert "simulated" in context["note"]
    assert context["facts"] == ["a fact"]
    assert len(context["metrics"]) <= MAX_CONTEXT_POINTS
    assert set(context["metrics"][0]) == {
        "ts", "up", "error_rate", "latency_p95_ms", "cpu_pct", "mem_pct", "request_rate"
    }  # fmt: skip
    assert "service_id" not in context["metrics"][0]  # only the incident's own service
