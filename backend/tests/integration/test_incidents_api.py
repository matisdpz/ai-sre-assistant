"""Read API and status changes, end to end over HTTP against PostgreSQL."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import TEST_INGEST_TOKEN

pytestmark = pytest.mark.integration

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
SERVICE = "payment-service"
MISSING_ID = "00000000-0000-0000-0000-000000000000"


def sample(i: int, service: str = SERVICE, **overrides: Any) -> dict[str, Any]:
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
    values.update(overrides)
    return values


def send(client: TestClient, samples: list[dict[str, Any]]) -> dict[str, Any]:
    response = client.post(
        "/api/v1/ingest/metrics",
        json={"samples": samples},
        headers={"Authorization": f"Bearer {TEST_INGEST_TOKEN}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def open_incident(client: TestClient, start: int = 0, service: str = SERVICE) -> str:
    """Three breaching samples: one warning high_error_rate incident. Returns its id."""
    body = send(client, [sample(start + i, service, error_rate=7) for i in range(3)])
    [decision] = body["decisions"]
    return decision["incident_id"]


# --- services and metrics -------------------------------------------------------------


def test_services_list_counts_active_incidents(db_client: TestClient) -> None:
    open_incident(db_client)

    services = {s["id"]: s for s in db_client.get("/api/v1/services").json()}

    assert set(services) == {"api-gateway", "payment-service", "database-service"}
    assert services[SERVICE]["active_incidents"] == 1
    assert services["api-gateway"]["active_incidents"] == 0


def test_metrics_are_returned_oldest_first_and_labelled_simulated(
    db_client: TestClient,
) -> None:
    send(db_client, [sample(i, error_rate=i) for i in range(5)])
    url = f"/api/v1/services/{SERVICE}/metrics"

    points = db_client.get(url).json()
    assert [p["error_rate"] for p in points] == [0, 1, 2, 3, 4]
    assert {p["source"] for p in points} == {"simulated"}

    latest_two = db_client.get(url, params={"limit": 2}).json()
    assert [p["error_rate"] for p in latest_two] == [3, 4]

    since = (T0 + timedelta(seconds=20)).isoformat()
    assert [p["error_rate"] for p in db_client.get(url, params={"since": since}).json()] == [3, 4]

    until = (T0 + timedelta(seconds=20)).isoformat()
    window = db_client.get(url, params={"until": until, "limit": 2}).json()
    assert [p["error_rate"] for p in window] == [1, 2]  # latest two up to `until`


def test_metrics_of_unknown_service_is_404(db_client: TestClient) -> None:
    assert db_client.get("/api/v1/services/ghost/metrics").status_code == 404


# --- reading incidents ----------------------------------------------------------------


def test_incidents_are_listed_newest_first_with_filters(db_client: TestClient) -> None:
    first = open_incident(db_client, start=0)
    second = open_incident(db_client, start=10, service="api-gateway")
    db_client.post(f"/api/v1/incidents/{first}/resolve")

    def ids(**params: Any) -> list[str]:
        return [i["id"] for i in db_client.get("/api/v1/incidents", params=params).json()]

    assert ids() == [second, first]
    assert ids(status="open") == [second]
    assert ids(status="resolved") == [first]
    assert ids(service_id=SERVICE) == [first]
    assert ids(limit=1, offset=1) == [first]
    assert db_client.get("/api/v1/incidents", params={"status": "bogus"}).status_code == 422


def test_incident_detail_has_evidence_and_timeline(db_client: TestClient) -> None:
    incident_id = open_incident(db_client)
    send(db_client, [sample(3 + i, error_rate=20) for i in range(3)])  # escalates

    detail = db_client.get(f"/api/v1/incidents/{incident_id}").json()

    assert detail["severity"] == "critical"
    assert detail["status"] == "open"
    assert [e["value"] for e in detail["evidence"]] == [20, 20, 20]
    assert [(e["kind"], e["actor"]) for e in detail["events"]] == [
        ("detected", "system"),
        ("escalated", "system"),
    ]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", ""),
        ("post", "/acknowledge"),
        ("post", "/resolve"),
    ],
)
def test_unknown_incident_is_404(db_client: TestClient, method: str, path: str) -> None:
    response = getattr(db_client, method)(f"/api/v1/incidents/{MISSING_ID}{path}")
    assert response.status_code == 404


# --- status changes -------------------------------------------------------------------


def test_acknowledge_then_resolve(db_client: TestClient) -> None:
    incident_id = open_incident(db_client)
    url = f"/api/v1/incidents/{incident_id}"

    acked = db_client.post(f"{url}/acknowledge", json={"note": "looking at it"}).json()
    assert acked["status"] == "acknowledged"
    assert acked["resolved_at"] is None

    resolved = db_client.post(f"{url}/resolve").json()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None

    changes = [e for e in resolved["events"] if e["kind"] == "status_changed"]
    assert [(e["actor"], e["from_status"], e["to_status"], e["note"]) for e in changes] == [
        ("user", "open", "acknowledged", "looking at it"),
        ("user", "acknowledged", "resolved", None),
    ]


def test_open_incident_can_be_resolved_directly(db_client: TestClient) -> None:
    incident_id = open_incident(db_client)
    response = db_client.post(f"/api/v1/incidents/{incident_id}/resolve")
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("acknowledge", "acknowledge"),  # already acknowledged
        ("resolve", "resolve"),  # resolved is final
        ("resolve", "acknowledge"),
    ],
)
def test_invalid_transition_is_409(db_client: TestClient, first: str, second: str) -> None:
    incident_id = open_incident(db_client)
    url = f"/api/v1/incidents/{incident_id}"
    assert db_client.post(f"{url}/{first}").status_code == 200

    response = db_client.post(f"{url}/{second}")

    assert response.status_code == 409
    assert "cannot change status" in response.json()["detail"]
    events = db_client.get(url).json()["events"]
    assert sum(e["kind"] == "status_changed" for e in events) == 1  # nothing recorded


def test_note_is_limited(db_client: TestClient) -> None:
    incident_id = open_incident(db_client)
    response = db_client.post(
        f"/api/v1/incidents/{incident_id}/acknowledge", json={"note": "x" * 2001}
    )
    assert response.status_code == 422


# --- detection and status together ----------------------------------------------------


def test_acknowledged_incident_still_escalates(db_client: TestClient) -> None:
    incident_id = open_incident(db_client)
    db_client.post(f"/api/v1/incidents/{incident_id}/acknowledge")

    body = send(db_client, [sample(3 + i, error_rate=20) for i in range(3)])

    assert [d["kind"] for d in body["decisions"]] == ["escalated"]
    detail = db_client.get(f"/api/v1/incidents/{incident_id}").json()
    assert (detail["status"], detail["severity"]) == ("acknowledged", "critical")


def test_recurrence_after_resolution_opens_a_new_incident(db_client: TestClient) -> None:
    first = open_incident(db_client, start=0)
    db_client.post(f"/api/v1/incidents/{first}/resolve")

    second = open_incident(db_client, start=3)

    assert second != first
    assert db_client.get(f"/api/v1/incidents/{first}").json()["status"] == "resolved"


def test_summary_counts_statuses_and_response_times(db_client: TestClient) -> None:
    empty = db_client.get("/api/v1/incidents/summary").json()
    assert empty == {
        "open": 0,
        "acknowledged": 0,
        "resolved": 0,
        "mtta_seconds": None,
        "mttr_seconds": None,
    }

    first = open_incident(db_client, start=0)
    open_incident(db_client, start=10, service="api-gateway")
    db_client.post(f"/api/v1/incidents/{first}/acknowledge")
    db_client.post(f"/api/v1/incidents/{first}/resolve")

    summary = db_client.get("/api/v1/incidents/summary").json()
    assert (summary["open"], summary["acknowledged"], summary["resolved"]) == (1, 0, 1)
    # Sample timestamps are in 2026-01-01 and the actions happen now: both are positive.
    assert summary["mtta_seconds"] > 0
    assert summary["mttr_seconds"] >= summary["mtta_seconds"]
