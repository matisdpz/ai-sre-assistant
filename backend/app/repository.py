"""Database queries. The only module that builds SQL; callers own the transaction."""

import uuid
from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Actor,
    Incident,
    IncidentDiagnosis,
    IncidentEvent,
    IncidentStatus,
    IncidentType,
    MetricSnapshot,
    Service,
)


def existing_service_ids(session: Session, service_ids: Collection[str]) -> set[str]:
    rows = session.scalars(select(Service.id).where(Service.id.in_(service_ids)))
    return set(rows)


def lock_service(session: Session, service_id: str) -> None:
    """Row lock held until commit: ingest requests for the same service run one at a time.

    Locking the service row (which always exists) rather than incidents (which may not
    exist yet) prevents two concurrent requests from opening the same incident twice.
    """
    session.execute(select(Service.id).where(Service.id == service_id).with_for_update())


def latest_snapshot_ts(session: Session, service_id: str) -> datetime | None:
    return session.scalar(
        select(func.max(MetricSnapshot.ts)).where(MetricSnapshot.service_id == service_id)
    )


def insert_snapshots(session: Session, rows: Sequence[dict[str, Any]]) -> list[datetime]:
    """Insert snapshots, skipping (service, ts) pairs already stored.

    Returns the timestamps actually inserted, so duplicates can be counted.
    """
    stmt = (
        insert(MetricSnapshot)
        .values(list(rows))
        .on_conflict_do_nothing(index_elements=["service_id", "ts"])
        .returning(MetricSnapshot.ts)
    )
    return list(session.scalars(stmt))


def recent_snapshots(session: Session, service_id: str, limit: int) -> list[MetricSnapshot]:
    """The latest `limit` snapshots of a service, oldest first."""
    newest_first = session.scalars(
        select(MetricSnapshot)
        .where(MetricSnapshot.service_id == service_id)
        .order_by(MetricSnapshot.ts.desc())
        .limit(limit)
    ).all()
    return list(reversed(newest_first))


def active_incidents(session: Session, service_id: str) -> dict[IncidentType, Incident]:
    """Unresolved incidents of a service, by type (at most one per type, see the index)."""
    incidents = session.scalars(
        select(Incident).where(
            Incident.service_id == service_id, Incident.status != IncidentStatus.RESOLVED
        )
    )
    return {incident.type: incident for incident in incidents}


def list_services(session: Session) -> list[tuple[Service, int]]:
    """Every service with its number of unresolved incidents."""
    active = (
        select(func.count(Incident.id))
        .where(Incident.service_id == Service.id, Incident.status != IncidentStatus.RESOLVED)
        .scalar_subquery()
    )
    return [
        (row[0], row[1]) for row in session.execute(select(Service, active).order_by(Service.id))
    ]


def get_service(session: Session, service_id: str) -> Service | None:
    return session.get(Service, service_id)


def snapshots_since(
    session: Session,
    service_id: str,
    since: datetime | None,
    limit: int,
    until: datetime | None = None,
) -> list[MetricSnapshot]:
    """The latest `limit` snapshots of a service in (since, until], oldest first."""
    query = select(MetricSnapshot).where(MetricSnapshot.service_id == service_id)
    if since is not None:
        query = query.where(MetricSnapshot.ts > since)
    if until is not None:
        query = query.where(MetricSnapshot.ts <= until)
    newest_first = session.scalars(query.order_by(MetricSnapshot.ts.desc()).limit(limit)).all()
    return list(reversed(newest_first))


def list_incidents(
    session: Session,
    *,
    status: IncidentStatus | None,
    service_id: str | None,
    limit: int,
    offset: int,
) -> list[Incident]:
    """Newest first."""
    query = select(Incident)
    if status is not None:
        query = query.where(Incident.status == status)
    if service_id is not None:
        query = query.where(Incident.service_id == service_id)
    query = query.order_by(Incident.detected_at.desc(), Incident.id).limit(limit).offset(offset)
    return list(session.scalars(query))


def get_incident(
    session: Session, incident_id: uuid.UUID, *, for_update: bool = False
) -> Incident | None:
    """An incident with its timeline loaded."""
    query = (
        select(Incident).where(Incident.id == incident_id).options(selectinload(Incident.events))
    )
    if for_update:
        query = query.with_for_update(of=Incident)
    return session.scalar(query)


def snapshots_between(
    session: Session, service_id: str, start: datetime, end: datetime, limit: int = 1000
) -> list[MetricSnapshot]:
    """Snapshots of a service with start <= ts <= end, oldest first."""
    return list(
        session.scalars(
            select(MetricSnapshot)
            .where(
                MetricSnapshot.service_id == service_id,
                MetricSnapshot.ts >= start,
                MetricSnapshot.ts <= end,
            )
            .order_by(MetricSnapshot.ts)
            .limit(limit)
        )
    )


def latest_diagnosis(session: Session, incident_id: uuid.UUID) -> IncidentDiagnosis | None:
    return session.scalar(
        select(IncidentDiagnosis)
        .where(IncidentDiagnosis.incident_id == incident_id)
        .order_by(IncidentDiagnosis.created_at.desc())
        .limit(1)
    )


def incident_summary(session: Session) -> dict[str, Any]:
    """Counts by status, plus MTTA and MTTR in seconds (None when there is no data yet).

    MTTA: detection -> first human status change. MTTR: detection -> resolution.
    """
    counts = dict(
        session.execute(select(Incident.status, func.count()).group_by(Incident.status)).all()
    )
    first_human_action = (
        select(IncidentEvent.incident_id, func.min(IncidentEvent.created_at).label("at"))
        .where(IncidentEvent.actor == Actor.USER)
        .group_by(IncidentEvent.incident_id)
        .subquery()
    )
    mtta = session.scalar(
        select(
            func.avg(func.extract("epoch", first_human_action.c.at - Incident.detected_at))
        ).join(first_human_action, first_human_action.c.incident_id == Incident.id)
    )
    mttr = session.scalar(
        select(func.avg(func.extract("epoch", Incident.resolved_at - Incident.detected_at))).where(
            Incident.resolved_at.is_not(None)
        )
    )
    return {
        "open": counts.get(IncidentStatus.OPEN, 0),
        "acknowledged": counts.get(IncidentStatus.ACKNOWLEDGED, 0),
        "resolved": counts.get(IncidentStatus.RESOLVED, 0),
        "mtta_seconds": float(mtta) if mtta is not None else None,
        "mttr_seconds": float(mttr) if mttr is not None else None,
    }
