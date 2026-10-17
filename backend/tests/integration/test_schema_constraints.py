"""The database enforces invariants on its own, independently of application code."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Incident, IncidentStatus, IncidentType, MetricSnapshot, Severity

pytestmark = pytest.mark.integration

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _snapshot(**overrides: object) -> MetricSnapshot:
    values = dict(
        service_id="payment-service",
        ts=T0,
        request_rate=120.0,
        error_rate=0.5,
        latency_p95_ms=180.0,
        cpu_pct=40.0,
        mem_pct=55.0,
        up=True,
    )
    values.update(overrides)
    return MetricSnapshot(**values)


def _incident(status: IncidentStatus = IncidentStatus.OPEN) -> Incident:
    return Incident(
        service_id="payment-service",
        type=IncidentType.HIGH_ERROR_RATE,
        severity=Severity.WARNING,
        status=status,
        summary="Error rate above 5%",
        threshold=5.0,
        peak_value=7.2,
        started_at=T0,
        detected_at=T0,
    )


def test_valid_snapshot_is_stored_with_simulated_source(db_session: Session) -> None:
    snapshot = _snapshot()
    db_session.add(snapshot)
    db_session.flush()
    db_session.refresh(snapshot)
    assert snapshot.source == "simulated"


@pytest.mark.parametrize(
    "field,value",
    [
        ("error_rate", 100.1),
        ("error_rate", -0.1),
        ("cpu_pct", 101.0),
        ("mem_pct", -1.0),
        ("request_rate", -5.0),
        ("latency_p95_ms", -1.0),
    ],
)
def test_out_of_range_metric_is_rejected(db_session: Session, field: str, value: float) -> None:
    db_session.add(_snapshot(**{field: value}))
    with pytest.raises(IntegrityError, match="ck_metric_snapshots"):
        db_session.flush()


@pytest.mark.parametrize("field,value", [("error_rate", 100.0), ("cpu_pct", 0.0)])
def test_percent_boundaries_are_accepted(db_session: Session, field: str, value: float) -> None:
    db_session.add(_snapshot(**{field: value}))
    db_session.flush()


def test_duplicate_sample_for_same_service_and_timestamp_is_rejected(db_session: Session) -> None:
    db_session.add(_snapshot())
    db_session.flush()
    db_session.add(_snapshot())
    with pytest.raises(IntegrityError, match="uq_metric_snapshots_service_id_ts"):
        db_session.flush()


def test_snapshot_for_unknown_service_is_rejected(db_session: Session) -> None:
    db_session.add(_snapshot(service_id="does-not-exist"))
    with pytest.raises(IntegrityError, match="fk_metric_snapshots_service_id_services"):
        db_session.flush()


def test_second_active_incident_of_same_type_is_rejected(db_session: Session) -> None:
    db_session.add(_incident(IncidentStatus.OPEN))
    db_session.flush()
    db_session.add(_incident(IncidentStatus.ACKNOWLEDGED))
    with pytest.raises(IntegrityError, match="uq_incidents_active_service_type"):
        db_session.flush()


def test_new_incident_is_allowed_once_previous_one_is_resolved(db_session: Session) -> None:
    db_session.add(_incident(IncidentStatus.RESOLVED))
    db_session.add(_incident(IncidentStatus.RESOLVED))
    db_session.add(_incident(IncidentStatus.OPEN))
    db_session.flush()


def test_unknown_incident_status_is_rejected_by_database(db_session: Session) -> None:
    db_session.add(_incident())
    db_session.flush()
    with pytest.raises(IntegrityError, match="ck_incidents_incident_status"):
        db_session.execute(
            Incident.__table__.update().values(status="closed")  # bypasses the Python enum
        )
