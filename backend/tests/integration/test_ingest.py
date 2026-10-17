"""Ingest workflow against PostgreSQL: storage, deduplication and the incident lifecycle."""

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app import repository
from app.incident_manager import UnknownServiceError, ingest
from app.models import (
    EventKind,
    Incident,
    IncidentEvent,
    IncidentStatus,
    IncidentType,
    MetricSnapshot,
    Severity,
)
from app.schemas import MetricSampleIn
from tests.conftest import TEST_INGEST_TOKEN

pytestmark = pytest.mark.integration

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
SERVICE = "payment-service"


def tick(i: int, service: str = SERVICE, **overrides: Any) -> MetricSampleIn:
    """A healthy simulated sample at T0 + i * 10 s, with some metrics overridden."""
    values: dict[str, Any] = {
        "service_id": service,
        "ts": T0 + timedelta(seconds=10 * i),
        "request_rate": 100.0,
        "error_rate": 1.0,
        "latency_p95_ms": 120.0,
        "cpu_pct": 30.0,
        "mem_pct": 40.0,
        "up": True,
    }
    values.update(overrides)
    return MetricSampleIn(**values)


def error_ticks(start: int, *rates: float) -> list[MetricSampleIn]:
    return [tick(start + i, error_rate=rate) for i, rate in enumerate(rates)]


def feed(session: Session, samples: list[MetricSampleIn]) -> list[EventKind]:
    """Send samples one tick per request, like the simulator; return decision kinds."""
    kinds = []
    for sample in samples:
        kinds += [applied.decision.kind for applied in ingest(session, [sample]).decisions]
    return kinds


def incidents(session: Session) -> list[Incident]:
    return list(session.scalars(select(Incident).order_by(Incident.detected_at)))


def event_kinds(session: Session, incident: Incident) -> list[EventKind]:
    query = (
        select(IncidentEvent.kind)
        .where(IncidentEvent.incident_id == incident.id)
        .order_by(IncidentEvent.id)
    )
    return list(session.scalars(query))


# --- storage and deduplication --------------------------------------------------------


def test_samples_are_stored_as_simulated(db_session: Session) -> None:
    result = ingest(db_session, [tick(0), tick(1), tick(0, service="api-gateway")])

    assert (result.stored, result.duplicates, result.late) == (3, 0, 0)
    sources = set(db_session.scalars(select(MetricSnapshot.source)))
    assert sources == {"simulated"}


def test_replayed_batch_is_ignored(db_session: Session) -> None:
    batch = error_ticks(0, 6, 7, 8)
    assert [d.decision.kind for d in ingest(db_session, batch).decisions] == [EventKind.DETECTED]

    replay = ingest(db_session, batch)

    assert (replay.stored, replay.duplicates, replay.decisions) == (0, 3, [])
    assert len(incidents(db_session)) == 1


def test_unknown_service_is_rejected_and_nothing_is_stored(db_session: Session) -> None:
    with pytest.raises(UnknownServiceError, match="ghost-service"):
        ingest(db_session, [tick(0), tick(0, service="ghost-service")])

    assert db_session.scalar(select(func.count()).select_from(MetricSnapshot)) == 0


def test_late_sample_is_stored_but_not_evaluated(db_session: Session) -> None:
    feed(db_session, [tick(5), tick(6)])

    result = ingest(db_session, error_ticks(0, 50, 50, 50))  # older than tick 6

    assert (result.stored, result.late, result.decisions) == (3, 3, [])
    assert incidents(db_session) == []


# --- incident lifecycle ---------------------------------------------------------------


def test_breach_opens_one_incident_with_evidence(db_session: Session) -> None:
    kinds = feed(db_session, [tick(0), *error_ticks(1, 6, 7, 8, 9)])

    assert kinds == [EventKind.DETECTED]
    [incident] = incidents(db_session)
    assert incident.type is IncidentType.HIGH_ERROR_RATE
    assert incident.severity is Severity.WARNING
    assert incident.status is IncidentStatus.OPEN
    assert incident.started_at == T0 + timedelta(seconds=10)
    assert incident.detected_at == T0 + timedelta(seconds=30)
    assert [e["value"] for e in incident.evidence] == [6, 7, 8]
    assert incident.peak_value == 9  # updated by the ongoing breach, without a new event
    assert event_kinds(db_session, incident) == [EventKind.DETECTED]


def test_one_batch_of_ticks_gives_the_same_result_as_one_tick_per_request(
    db_session: Session,
) -> None:
    result = ingest(db_session, error_ticks(0, 6, 7, 8, 12, 13, 14, 1, 1, 1))

    assert [d.decision.kind for d in result.decisions] == [
        EventKind.DETECTED,
        EventKind.ESCALATED,
        EventKind.RECOVERED,
    ]
    assert len(incidents(db_session)) == 1


def test_full_lifecycle_escalate_recover_retrigger(db_session: Session) -> None:
    feed(db_session, error_ticks(0, 6, 7, 8))
    assert feed(db_session, error_ticks(3, 12, 13, 14)) == [EventKind.ESCALATED]
    [incident] = incidents(db_session)
    assert (incident.severity, incident.threshold) == (Severity.CRITICAL, 10.0)

    assert feed(db_session, error_ticks(6, 1, 1, 1)) == [EventKind.RECOVERED]
    db_session.refresh(incident)
    assert incident.recovered_at == T0 + timedelta(seconds=60)
    assert incident.status is IncidentStatus.OPEN  # recovery never resolves

    assert feed(db_session, error_ticks(9, 6, 6, 6)) == [EventKind.RETRIGGERED]
    db_session.refresh(incident)
    assert incident.recovered_at is None
    assert incident.severity is Severity.CRITICAL  # never downgrades
    assert incident.peak_value == 14
    assert event_kinds(db_session, incident) == [
        EventKind.DETECTED,
        EventKind.ESCALATED,
        EventKind.RECOVERED,
        EventKind.RETRIGGERED,
    ]
    assert len(incidents(db_session)) == 1


def test_breach_after_resolution_opens_a_new_incident(db_session: Session) -> None:
    feed(db_session, error_ticks(0, 6, 7, 8))
    [first] = incidents(db_session)
    first.status = IncidentStatus.RESOLVED  # as the resolve endpoint does
    db_session.commit()

    assert feed(db_session, error_ticks(3, 6, 7, 8)) == [EventKind.DETECTED]
    assert len(incidents(db_session)) == 2


def test_services_are_evaluated_independently(db_session: Session) -> None:
    batch = [
        tick(i, service=service, up=service != "database-service")
        for i in range(2)
        for service in ("api-gateway", "database-service")
    ]
    result = ingest(db_session, batch)

    assert [(d.service_id, d.decision.incident_type) for d in result.decisions] == [
        ("database-service", IncidentType.SERVICE_DOWN)
    ]


# --- concurrency ----------------------------------------------------------------------


def test_concurrent_requests_do_not_open_the_same_incident_twice(
    clean_db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(clean_db) as session:
        ingest(session, error_ticks(0, 6, 7))  # two breaching samples: one more opens it

    # Slow down the read of active incidents so both requests overlap in the worst place:
    # without the service lock, both would see "no incident" and both would open one.
    read_active = repository.active_incidents

    def slow_read_active(session: Session, service_id: str) -> dict:
        found = read_active(session, service_id)
        time.sleep(0.3)
        return found

    monkeypatch.setattr(repository, "active_incidents", slow_read_active)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def send(i: int) -> None:
        try:
            with Session(clean_db) as session:
                barrier.wait()
                ingest(session, error_ticks(i, 8))
        except BaseException as exc:  # reported to the main thread below
            errors.append(exc)

    threads = [threading.Thread(target=send, args=(i,)) for i in (2, 3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    with Session(clean_db) as session:
        assert len(incidents(session)) == 1


# --- HTTP, end to end -----------------------------------------------------------------


def _post(client: TestClient, samples: list[MetricSampleIn]) -> Any:
    body = {"samples": [s.model_dump(mode="json") for s in samples]}
    return client.post(
        "/api/v1/ingest/metrics",
        json=body,
        headers={"Authorization": f"Bearer {TEST_INGEST_TOKEN}"},
    )


def test_api_reports_decisions(db_client: TestClient) -> None:
    response = _post(db_client, error_ticks(0, 12, 12, 12))

    assert response.status_code == 200
    body = response.json()
    assert (body["stored"], body["duplicates"], body["late"]) == (3, 0, 0)
    [decision] = body["decisions"]
    assert decision["service_id"] == SERVICE
    assert decision["type"] == "high_error_rate"
    assert decision["kind"] == "detected"
    assert decision["severity"] == "critical"


def test_api_rejects_unknown_service(db_client: TestClient) -> None:
    response = _post(db_client, [tick(0, service="ghost-service")])

    assert response.status_code == 422
    assert "ghost-service" in response.json()["detail"]
