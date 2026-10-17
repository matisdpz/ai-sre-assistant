"""Ingest workflow: store simulated metric samples, run detection, persist its decisions.

Detection itself (app/detection.py) is pure; this module is the imperative shell around
it. One call is one transaction: either the whole batch and its incidents are saved, or
nothing is.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import repository
from app.detection import RULES, ActiveIncident, Decision, Sample, evaluate_all, level
from app.models import (
    Actor,
    EventKind,
    Incident,
    IncidentEvent,
    IncidentStatus,
    IncidentType,
    MetricSnapshot,
)
from app.schemas import MetricSampleIn

# Samples given to each rule evaluation. Must cover the largest N and M.
DETECTION_WINDOW = 20
_RULES = {rule.incident_type: rule for rule in RULES}


class UnknownServiceError(Exception):
    def __init__(self, service_ids: Sequence[str]) -> None:
        self.service_ids = list(service_ids)
        super().__init__(f"unknown service(s): {', '.join(self.service_ids)}")


@dataclass(frozen=True)
class AppliedDecision:
    incident_id: uuid.UUID
    service_id: str
    decision: Decision


@dataclass
class IngestResult:
    stored: int = 0
    duplicates: int = 0
    late: int = 0
    decisions: list[AppliedDecision] = field(default_factory=list)


def ingest(session: Session, samples: Sequence[MetricSampleIn]) -> IngestResult:
    by_service: dict[str, list[MetricSampleIn]] = defaultdict(list)
    for sample in samples:
        by_service[sample.service_id].append(sample)

    unknown = set(by_service) - repository.existing_service_ids(session, by_service.keys())
    if unknown:
        raise UnknownServiceError(sorted(unknown))

    result = IngestResult()
    # Sorted, so concurrent requests always lock services in the same order (no deadlock).
    for service_id in sorted(by_service):
        repository.lock_service(session, service_id)
        previous_latest = repository.latest_snapshot_ts(session, service_id)
        inserted = repository.insert_snapshots(
            session, [s.model_dump() for s in by_service[service_id]]
        )
        result.stored += len(inserted)

        # Only samples newer than everything already stored are evaluated. A late sample
        # is kept as data, but replaying the past would contradict decisions already made.
        new = sorted(ts for ts in inserted if previous_latest is None or ts > previous_latest)
        result.late += len(inserted) - len(new)
        if new:
            result.decisions += _detect(session, service_id, len(new))

    result.duplicates = len(samples) - result.stored
    session.commit()
    return result


def _detect(session: Session, service_id: str, new_count: int) -> list[AppliedDecision]:
    """Evaluate the rules once per new sample, in timestamp order.

    Evaluating sample by sample (not only the batch's last one) means a batch holding
    several ticks gives the same incidents as the same ticks sent one at a time.
    """
    rows = repository.recent_snapshots(session, service_id, DETECTION_WINDOW - 1 + new_count)
    samples = [_to_sample(row) for row in rows]
    incidents = repository.active_incidents(session, service_id)
    applied = []

    for end in range(len(samples) - new_count + 1, len(samples) + 1):
        window = samples[max(0, end - DETECTION_WINDOW) : end]
        active = {
            type_: ActiveIncident(incident.severity, recovered=incident.recovered_at is not None)
            for type_, incident in incidents.items()
        }
        for decision in evaluate_all(window, active):
            incident = _apply(session, service_id, incidents.get(decision.incident_type), decision)
            incidents[decision.incident_type] = incident
            applied.append(AppliedDecision(incident.id, service_id, decision))
        _update_peaks(incidents, window[-1])

    return applied


def _apply(
    session: Session, service_id: str, incident: Incident | None, decision: Decision
) -> Incident:
    if decision.kind is EventKind.DETECTED:
        incident = Incident(
            id=uuid.uuid4(),
            service_id=service_id,
            type=decision.incident_type,
            severity=decision.severity,
            status=IncidentStatus.OPEN,
            summary=decision.summary,
            threshold=decision.threshold,
            peak_value=decision.peak_value,
            started_at=decision.started_at,
            detected_at=decision.at,
            evidence=decision.evidence,
        )
        session.add(incident)
    elif incident is None:
        # evaluate() only returns other kinds when an active incident was passed in.
        raise RuntimeError(f"{decision.kind} decision without an active incident")
    elif decision.kind is EventKind.RECOVERED:
        incident.recovered_at = decision.at
    else:  # ESCALATED or RETRIGGERED
        incident.severity = decision.severity
        incident.threshold = decision.threshold
        incident.peak_value = max(incident.peak_value, decision.peak_value)
        incident.summary = decision.summary
        incident.evidence = decision.evidence
        incident.recovered_at = None

    session.add(
        IncidentEvent(
            incident_id=incident.id, kind=decision.kind, actor=Actor.SYSTEM, note=decision.summary
        )
    )
    return incident


def _update_peaks(incidents: dict[IncidentType, Incident], latest: Sample) -> None:
    """Keep the worst value seen while an incident is ongoing (no event: not a decision)."""
    for type_, incident in incidents.items():
        rule = _RULES[type_]
        if incident.recovered_at is not None or (rule.skip_when_down and not latest.up):
            continue
        if level(rule, latest) is not None:
            incident.peak_value = max(incident.peak_value, rule.value(latest))


def _to_sample(row: MetricSnapshot) -> Sample:
    return Sample(
        ts=row.ts,
        error_rate=row.error_rate,
        latency_p95_ms=row.latency_p95_ms,
        cpu_pct=row.cpu_pct,
        up=row.up,
    )
