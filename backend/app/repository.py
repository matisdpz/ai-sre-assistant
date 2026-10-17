"""Database queries. The only module that builds SQL; callers own the transaction."""

from collections.abc import Collection, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Incident, IncidentStatus, IncidentType, MetricSnapshot, Service


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
