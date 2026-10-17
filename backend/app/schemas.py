import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models import Actor, EventKind, IncidentStatus, IncidentType, Severity

MAX_BATCH_SAMPLES = 500


class LiveResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, Literal["ok", "error"]]


class MetricSampleIn(BaseModel):
    """One simulated metric snapshot of one service."""

    # Reject unknown fields and NaN/Infinity: they would silently break thresholds.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    service_id: str = Field(min_length=1, max_length=64)
    ts: AwareDatetime  # naive timestamps are ambiguous, so they are rejected
    request_rate: float = Field(ge=0)
    error_rate: float = Field(ge=0, le=100)
    latency_p95_ms: float = Field(ge=0)
    cpu_pct: float = Field(ge=0, le=100)
    mem_pct: float = Field(ge=0, le=100)
    up: bool


class MetricBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    samples: list[MetricSampleIn] = Field(min_length=1, max_length=MAX_BATCH_SAMPLES)


class IncidentDecisionOut(BaseModel):
    incident_id: uuid.UUID
    service_id: str
    type: IncidentType
    kind: EventKind
    severity: Severity


class IngestResponse(BaseModel):
    stored: int  # new snapshots written
    duplicates: int  # already stored (same service and timestamp), ignored
    late: int  # stored, but older than the latest sample: not evaluated
    decisions: list[IncidentDecisionOut]


# --- read API ---------------------------------------------------------------------------


class ServiceOut(BaseModel):
    id: str
    name: str
    description: str
    active_incidents: int  # unresolved


class MetricPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ts: datetime
    request_rate: float
    error_rate: float
    latency_p95_ms: float
    cpu_pct: float
    mem_pct: float
    up: bool
    source: str  # always "simulated" in this project


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service_id: str
    type: IncidentType
    severity: Severity
    status: IncidentStatus
    summary: str
    threshold: float
    peak_value: float
    started_at: datetime
    detected_at: datetime
    recovered_at: datetime | None
    resolved_at: datetime | None
    updated_at: datetime


class IncidentSummaryOut(BaseModel):
    open: int
    acknowledged: int
    resolved: int
    mtta_seconds: float | None  # mean time to acknowledge: detection -> first human action
    mttr_seconds: float | None  # mean time to resolve: detection -> resolution


class IncidentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: EventKind
    actor: Actor
    from_status: IncidentStatus | None
    to_status: IncidentStatus | None
    note: str | None
    created_at: datetime


class IncidentDetailOut(IncidentOut):
    evidence: list[dict[str, Any]]  # the samples behind the latest decision
    events: list[IncidentEventOut]  # timeline, oldest first


class StatusChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


class RuleOut(BaseModel):
    type: IncidentType
    label: str
    metric: str
    unit: str
    warning: float | None
    critical: float
    breach_samples: int
    recovery_samples: int


# --- AI diagnosis -----------------------------------------------------------------------


class AIStatusOut(BaseModel):
    enabled: bool
    provider: str | None
    model: str | None


class HypothesisOut(BaseModel):
    title: str
    reasoning: str
    confidence: Literal["low", "medium", "high"]
    supporting_facts: list[str]


class DiagnosisOut(BaseModel):
    """`facts` are observed (computed from stored data); the rest is AI-generated."""

    id: uuid.UUID
    incident_id: uuid.UUID
    provider: str
    model: str
    created_at: datetime
    facts: list[str]
    summary: str
    hypotheses: list[HypothesisOut]
    suggested_checks: list[str]
    disclaimer: str = (
        "AI-generated hypotheses from simulated data. Not a confirmed root cause: "
        "verify before acting."
    )
