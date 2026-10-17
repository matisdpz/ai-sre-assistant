"""Initial schema: services, metric snapshots, incidents and incident events.

Revision ID: 0001
Revises:
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum values are copied here on purpose: a migration must keep describing the
# schema as it was at this revision, even after the application enums change.
INCIDENT_TYPES = ("high_error_rate", "high_latency", "high_cpu", "service_down")
SEVERITIES = ("warning", "critical")
STATUSES = ("open", "acknowledged", "resolved")
EVENT_KINDS = ("detected", "escalated", "recovered", "retriggered", "status_changed")
ACTORS = ("system", "user")

SEED_SERVICES = [
    {
        "id": "api-gateway",
        "name": "API Gateway",
        "description": "Entry point that routes client requests to backend services.",
    },
    {
        "id": "payment-service",
        "name": "Payment Service",
        "description": "Processes payments; depends on the database service.",
    },
    {
        "id": "database-service",
        "name": "Database Service",
        "description": "Primary data store used by the payment service.",
    },
]


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    services = op.create_table(
        "services",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_services")),
    )

    op.create_table(
        "metric_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("service_id", sa.String(64), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_rate", sa.Float(), nullable=False),
        sa.Column("error_rate", sa.Float(), nullable=False),
        sa.Column("latency_p95_ms", sa.Float(), nullable=False),
        sa.Column("cpu_pct", sa.Float(), nullable=False),
        sa.Column("mem_pct", sa.Float(), nullable=False),
        sa.Column("up", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(32), server_default="simulated", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_snapshots")),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            name=op.f("fk_metric_snapshots_service_id_services"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("service_id", "ts", name=op.f("uq_metric_snapshots_service_id_ts")),
        sa.CheckConstraint(
            "request_rate >= 0", name=op.f("ck_metric_snapshots_request_rate_non_negative")
        ),
        sa.CheckConstraint(
            "error_rate BETWEEN 0 AND 100", name=op.f("ck_metric_snapshots_error_rate_percent")
        ),
        sa.CheckConstraint(
            "latency_p95_ms >= 0", name=op.f("ck_metric_snapshots_latency_non_negative")
        ),
        sa.CheckConstraint("cpu_pct BETWEEN 0 AND 100", name=op.f("ck_metric_snapshots_cpu_percent")),
        sa.CheckConstraint("mem_pct BETWEEN 0 AND 100", name=op.f("ck_metric_snapshots_mem_percent")),
    )

    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("peak_value", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            name=op.f("fk_incidents_service_id_services"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_in("type", INCIDENT_TYPES), name=op.f("ck_incidents_incident_type")),
        sa.CheckConstraint(_in("severity", SEVERITIES), name=op.f("ck_incidents_severity")),
        sa.CheckConstraint(_in("status", STATUSES), name=op.f("ck_incidents_incident_status")),
    )
    op.create_index(
        "uq_incidents_active_service_type",
        "incidents",
        ["service_id", "type"],
        unique=True,
        postgresql_where=sa.text("status <> 'resolved'"),
    )
    op.create_index("ix_incidents_detected_at", "incidents", ["detected_at"])

    op.create_table(
        "incident_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incident_events")),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_incident_events_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(_in("kind", EVENT_KINDS), name=op.f("ck_incident_events_event_kind")),
        sa.CheckConstraint(_in("actor", ACTORS), name=op.f("ck_incident_events_actor")),
        sa.CheckConstraint(
            _in("from_status", STATUSES), name=op.f("ck_incident_events_event_from_status")
        ),
        sa.CheckConstraint(
            _in("to_status", STATUSES), name=op.f("ck_incident_events_event_to_status")
        ),
    )
    op.create_index(
        "ix_incident_events_incident_created", "incident_events", ["incident_id", "created_at"]
    )

    op.bulk_insert(services, SEED_SERVICES)


def downgrade() -> None:
    op.drop_table("incident_events")
    op.drop_table("incidents")
    op.drop_table("metric_snapshots")
    op.drop_table("services")
