import uuid
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models import EventKind, IncidentType, Severity

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
