import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Predictable constraint names, so Alembic migrations can reference them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IncidentType(StrEnum):
    HIGH_ERROR_RATE = "high_error_rate"
    HIGH_LATENCY = "high_latency"
    HIGH_CPU = "high_cpu"
    SERVICE_DOWN = "service_down"


class Severity(StrEnum):
    WARNING = "warning"
    CRITICAL = "critical"


class IncidentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class EventKind(StrEnum):
    DETECTED = "detected"
    ESCALATED = "escalated"
    RECOVERED = "recovered"
    RETRIGGERED = "retriggered"
    STATUS_CHANGED = "status_changed"


class Actor(StrEnum):
    SYSTEM = "system"
    USER = "user"


def _str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    # Stored as VARCHAR + CHECK rather than a native Postgres ENUM type:
    # adding a value later is a simple constraint change in a migration.
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [member.value for member in e],
    )


class Service(Base):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MetricSnapshot(Base):
    """All metrics of one service at one instant (one row per service per tick)."""

    __tablename__ = "metric_snapshots"
    __table_args__ = (
        # Also serves as the index for "metrics of service X over time" queries,
        # and makes re-ingesting the same sample impossible.
        UniqueConstraint("service_id", "ts"),
        CheckConstraint("request_rate >= 0", name="request_rate_non_negative"),
        CheckConstraint("error_rate BETWEEN 0 AND 100", name="error_rate_percent"),
        CheckConstraint("latency_p95_ms >= 0", name="latency_non_negative"),
        CheckConstraint("cpu_pct BETWEEN 0 AND 100", name="cpu_percent"),
        CheckConstraint("mem_pct BETWEEN 0 AND 100", name="mem_percent"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_rate: Mapped[float] = mapped_column(Float)  # requests per second
    error_rate: Mapped[float] = mapped_column(Float)  # percent of requests, 0-100
    latency_p95_ms: Mapped[float] = mapped_column(Float)  # milliseconds
    cpu_pct: Mapped[float] = mapped_column(Float)  # percent, 0-100
    mem_pct: Mapped[float] = mapped_column(Float)  # percent, 0-100
    up: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(32), server_default="simulated")


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        # Deduplication guarantee: at most one unresolved incident per service and type.
        Index(
            "uq_incidents_active_service_type",
            "service_id",
            "type",
            unique=True,
            postgresql_where=text("status <> 'resolved'"),
        ),
        Index("ix_incidents_detected_at", "detected_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"))
    type: Mapped[IncidentType] = mapped_column(_str_enum(IncidentType, "incident_type"))
    severity: Mapped[Severity] = mapped_column(_str_enum(Severity, "severity"))
    status: Mapped[IncidentStatus] = mapped_column(
        _str_enum(IncidentStatus, "incident_status"), default=IncidentStatus.OPEN
    )
    summary: Mapped[str] = mapped_column(Text)
    threshold: Mapped[float] = mapped_column(Float)
    peak_value: Mapped[float] = mapped_column(Float)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # first breaching sample
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # The samples that triggered the incident, kept as observed facts.
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )

    events: Mapped[list["IncidentEvent"]] = relationship(
        back_populates="incident",
        # Insertion order: events written in one transaction share the same created_at.
        order_by="IncidentEvent.id",
        cascade="all, delete-orphan",
    )


class IncidentEvent(Base):
    """Timeline entry: detection, escalation, recovery and status changes."""

    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_created", "incident_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"))
    kind: Mapped[EventKind] = mapped_column(_str_enum(EventKind, "event_kind"))
    actor: Mapped[Actor] = mapped_column(_str_enum(Actor, "actor"))
    from_status: Mapped[IncidentStatus | None] = mapped_column(
        _str_enum(IncidentStatus, "event_from_status")
    )
    to_status: Mapped[IncidentStatus | None] = mapped_column(
        _str_enum(IncidentStatus, "event_to_status")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    incident: Mapped[Incident] = relationship(back_populates="events")
