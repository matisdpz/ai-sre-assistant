"""Optional AI-assisted diagnosis of one incident, on explicit user request.

Observed facts are computed here, deterministically, from stored data. The AI provider
only adds hypotheses and suggested checks on top of them, so generated text can never
pass for an observation.
"""

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app import repository
from app.ai import DiagnosisProvider
from app.detection import RULES
from app.incident_manager import IncidentNotFoundError
from app.models import EventKind, Incident, IncidentDiagnosis, IncidentType, MetricSnapshot

CONTEXT_BEFORE = timedelta(minutes=15)  # baseline window before the incident started
CONTEXT_AFTER = timedelta(minutes=2)
MAX_CONTEXT_POINTS = 60  # downsampled series sent to the model (keeps prompts small)
SIGNIFICANT_CHANGE = 0.3  # relative change of a metric average worth reporting

_RULES = {rule.incident_type: rule for rule in RULES}
_METRICS = (  # (field, label, unit)
    ("error_rate", "error rate", "%"),
    ("latency_p95_ms", "p95 latency", "ms"),
    ("cpu_pct", "CPU usage", "%"),
    ("mem_pct", "memory usage", "%"),
    ("request_rate", "request rate", "req/s"),
)


def request_diagnosis(
    session: Session, incident_id: uuid.UUID, provider: DiagnosisProvider
) -> IncidentDiagnosis:
    incident = repository.get_incident(session, incident_id)
    if incident is None:
        raise IncidentNotFoundError(str(incident_id))

    end = incident.recovered_at or incident.resolved_at or incident.updated_at
    samples = repository.snapshots_between(
        session, incident.service_id, incident.started_at - CONTEXT_BEFORE, end + CONTEXT_AFTER
    )
    facts = compute_facts(incident, samples)
    context = build_context(incident, facts, samples)
    # End the read transaction before the slow network call: a request waiting up to 20 s
    # for the AI must not keep a database transaction (and its connection) open.
    session.commit()

    result = provider.diagnose(context)  # AIError propagates; nothing is stored then

    diagnosis = IncidentDiagnosis(
        id=uuid.uuid4(),
        incident_id=incident.id,
        provider=provider.name,
        model=provider.model,
        facts=facts,
        result=result.model_dump(),
    )
    session.add(diagnosis)
    session.commit()
    session.refresh(diagnosis)
    return diagnosis


def compute_facts(incident: Incident, samples: Sequence[MetricSnapshot]) -> list[str]:
    """Observed facts, from stored data only. Pure: no I/O."""
    rule = _RULES[incident.type]
    unit = f" {rule.unit}" if rule.unit else ""
    facts = [
        f"Incident type {incident.type.value} ({rule.label}) on {incident.service_id} "
        f"(simulated telemetry), "
        f"severity {incident.severity}, status {incident.status}.",
        f"First breaching sample at {incident.started_at.isoformat()}, "
        f"detected at {incident.detected_at.isoformat()}.",
    ]
    if incident.type is not IncidentType.SERVICE_DOWN:
        facts.append(
            f"Peak {rule.label}: {incident.peak_value:g}{unit} "
            f"(threshold for {incident.severity}: {incident.threshold:g}{unit})."
        )

    kinds = [event.kind for event in incident.events]
    if EventKind.ESCALATED in kinds:
        facts.append("Escalated from warning to critical while ongoing.")
    retriggers = kinds.count(EventKind.RETRIGGERED)
    if retriggers:
        facts.append(f"Metrics recovered and breached again {retriggers} time(s).")
    if incident.recovered_at is not None:
        duration = incident.recovered_at - incident.started_at
        facts.append(f"Metrics recovered after {_duration(duration)}.")
    elif samples:
        facts.append(
            f"Not recovered at the last stored sample, "
            f"{_duration(samples[-1].ts - incident.started_at)} after the start."
        )

    end = incident.recovered_at or (samples[-1].ts if samples else incident.started_at)
    before = [s for s in samples if s.ts < incident.started_at]
    during = [s for s in samples if incident.started_at <= s.ts <= end]

    down = sum(not s.up for s in during)
    if down:
        facts.append(f"The service reported down in {down} of {len(during)} samples during it.")

    before_up = [s for s in before if s.up]
    during_up = [s for s in during if s.up]
    if not before_up:
        facts.append("No healthy samples before the start are stored, so no baseline exists.")
    elif during_up:
        for field, label, metric_unit in _METRICS:
            avg_before = _mean(getattr(s, field) for s in before_up)
            avg_during = _mean(getattr(s, field) for s in during_up)
            change = (avg_during - avg_before) / avg_before if avg_before else None
            if change is not None and abs(change) >= SIGNIFICANT_CHANGE:
                facts.append(
                    f"Average {label}: {avg_before:.1f} {metric_unit} before the incident, "
                    f"{avg_during:.1f} {metric_unit} during it ({change:+.0%})."
                )
    return facts


def build_context(
    incident: Incident, facts: list[str], samples: Sequence[MetricSnapshot]
) -> dict[str, Any]:
    """Everything sent to the provider: this incident and its own service's metrics only."""
    rule = _RULES[incident.type]
    step = max(1, -(-len(samples) // MAX_CONTEXT_POINTS))  # ceil division
    return {
        "note": "All telemetry is simulated. Facts were computed from stored samples.",
        "incident": {
            "type": incident.type.value,
            "service_id": incident.service_id,
            "severity": incident.severity.value,
            "status": incident.status.value,
            "summary": incident.summary,
            "started_at": incident.started_at.isoformat(),
            "detected_at": incident.detected_at.isoformat(),
            "recovered_at": incident.recovered_at.isoformat() if incident.recovered_at else None,
            "timeline": [event.kind.value for event in incident.events],
        },
        "facts": facts,
        "detection_rule": {
            "metric": rule.label,
            "unit": rule.unit,
            "warning": rule.warning,
            "critical": rule.critical,
            "breach_samples": rule.breach_samples,
            "recovery_samples": rule.recovery_samples,
        },
        "metrics": [
            {
                "ts": s.ts.isoformat(),
                "up": s.up,
                "error_rate": s.error_rate,
                "latency_p95_ms": s.latency_p95_ms,
                "cpu_pct": s.cpu_pct,
                "mem_pct": s.mem_pct,
                "request_rate": s.request_rate,
            }
            for s in samples[::step]
        ],
    }


def _mean(values: Any) -> float:
    items = list(values)
    return sum(items) / len(items)


def _duration(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 120:
        return f"{seconds} s"
    return f"{seconds // 60} min"
