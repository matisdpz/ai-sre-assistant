"""Deterministic incident detection rules.

Everything here is pure: no database, no I/O and no wall clock. Time comes only from
sample timestamps, so the same samples always produce the same decisions. The incident
manager (`app/incident_manager.py`) feeds recent samples and the current incident state in, and
persists the returned decisions.

All telemetry in this project is simulated.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models import EventKind, IncidentType, Severity


@dataclass(frozen=True)
class Sample:
    """One metric snapshot of one service (simulated telemetry)."""

    ts: datetime
    error_rate: float  # percent, 0-100
    latency_p95_ms: float
    cpu_pct: float  # percent, 0-100
    up: bool


@dataclass(frozen=True)
class Rule:
    incident_type: IncidentType
    label: str
    unit: str
    value: Callable[[Sample], float]
    warning: float | None  # None: the rule has a single (critical) level
    critical: float
    breach_samples: int  # N consecutive breaching samples open (or escalate) an incident
    recovery_samples: int  # M consecutive healthy samples mark it recovered
    # Metric rules skip samples from a down service: a crashed service reports
    # meaningless values (e.g. 0 ms latency) that must not count as a recovery.
    skip_when_down: bool = True


RULES: tuple[Rule, ...] = (
    Rule(
        IncidentType.HIGH_ERROR_RATE, "error rate", "%",
        lambda s: s.error_rate, warning=5.0, critical=10.0,
        breach_samples=3, recovery_samples=3,
    ),
    Rule(
        IncidentType.HIGH_LATENCY, "p95 latency", "ms",
        lambda s: s.latency_p95_ms, warning=500.0, critical=1000.0,
        breach_samples=3, recovery_samples=3,
    ),
    Rule(
        IncidentType.HIGH_CPU, "CPU usage", "%",
        lambda s: s.cpu_pct, warning=85.0, critical=95.0,
        breach_samples=5, recovery_samples=3,
    ),
    Rule(
        # Encoded as 1.0 = down, 0.0 = up, so it fits the same threshold logic.
        IncidentType.SERVICE_DOWN, "service down", "",
        lambda s: 0.0 if s.up else 1.0, warning=None, critical=1.0,
        breach_samples=2, recovery_samples=2, skip_when_down=False,
    ),
)  # fmt: skip

_RANK = {Severity.WARNING: 1, Severity.CRITICAL: 2}


@dataclass(frozen=True)
class ActiveIncident:
    """The state of the unresolved incident for one service and rule."""

    severity: Severity
    recovered: bool


@dataclass(frozen=True)
class Decision:
    kind: EventKind  # DETECTED, ESCALATED, RECOVERED or RETRIGGERED
    incident_type: IncidentType
    severity: Severity
    at: datetime  # when it happened, taken from sample timestamps
    started_at: datetime  # first sample of the breaching (or healthy) run
    threshold: float  # threshold of the reported severity
    peak_value: float  # worst value in the run (for RECOVERED: worst value in the window)
    summary: str
    evidence: list[dict[str, Any]]  # the samples behind the decision: observed facts


def level(rule: Rule, sample: Sample) -> Severity | None:
    """Severity of a single sample, or None when it is healthy. Thresholds use >=."""
    value = rule.value(sample)
    if value >= rule.critical:
        return Severity.CRITICAL
    if rule.warning is not None and value >= rule.warning:
        return Severity.WARNING
    return None


def evaluate(
    rule: Rule, samples: Sequence[Sample], active: ActiveIncident | None
) -> Decision | None:
    """Decide what changes for one rule, given one service's recent samples.

    `samples` must be sorted by timestamp, oldest first, without duplicates.
    Returns None when nothing changes.
    """
    _check_sorted(samples)
    relevant = [s for s in samples if not (rule.skip_when_down and not s.up)]
    if not relevant:
        return None

    sustained = _sustained_severity(rule, relevant)

    if active is None:
        if sustained is None:
            return None
        return _breach_decision(rule, relevant, EventKind.DETECTED, sustained)

    if active.recovered:
        if sustained is None:
            return None
        # Severity never downgrades, even across a recovery.
        severity = max(sustained, active.severity, key=_RANK.__getitem__)
        return _breach_decision(rule, relevant, EventKind.RETRIGGERED, severity)

    if sustained is Severity.CRITICAL and active.severity is Severity.WARNING:
        return _breach_decision(rule, relevant, EventKind.ESCALATED, Severity.CRITICAL)

    window = relevant[-rule.recovery_samples :]
    if len(window) == rule.recovery_samples and all(level(rule, s) is None for s in window):
        return _recovery_decision(rule, window, active.severity)

    return None


def evaluate_all(
    samples: Sequence[Sample], active: Mapping[IncidentType, ActiveIncident]
) -> list[Decision]:
    """Run every rule on one service's samples. `active` maps type -> unresolved incident."""
    decisions = []
    for rule in RULES:
        decision = evaluate(rule, samples, active.get(rule.incident_type))
        if decision is not None:
            decisions.append(decision)
    return decisions


def _check_sorted(samples: Sequence[Sample]) -> None:
    for previous, current in zip(samples, samples[1:], strict=False):
        if current.ts <= previous.ts:
            raise ValueError("samples must be sorted by timestamp without duplicates")


def _sustained_severity(rule: Rule, samples: Sequence[Sample]) -> Severity | None:
    """Severity held by each of the last N samples (the lowest of them), or None."""
    window = samples[-rule.breach_samples :]
    if len(window) < rule.breach_samples:
        return None
    levels = [level(rule, s) for s in window]
    if any(lv is None for lv in levels):
        return None
    return min(levels, key=_RANK.__getitem__)


def _breach_decision(
    rule: Rule, samples: Sequence[Sample], kind: EventKind, severity: Severity
) -> Decision:
    # Walk back to the first sample of the current breaching run.
    run_start = len(samples)
    while run_start > 0 and level(rule, samples[run_start - 1]) is not None:
        run_start -= 1
    run = samples[run_start:]
    threshold = _threshold(rule, severity)
    peak = max(rule.value(s) for s in run)
    return Decision(
        kind=kind,
        incident_type=rule.incident_type,
        severity=severity,
        at=samples[-1].ts,
        started_at=run[0].ts,
        threshold=threshold,
        peak_value=peak,
        summary=_breach_summary(rule, severity, threshold, peak, len(run)),
        evidence=_evidence(rule, samples[-rule.breach_samples :]),
    )


def _recovery_decision(rule: Rule, window: Sequence[Sample], severity: Severity) -> Decision:
    peak = max(rule.value(s) for s in window)
    if rule.incident_type is IncidentType.SERVICE_DOWN:
        summary = f"service up again for {len(window)} consecutive samples"
    else:
        summary = (
            f"{rule.label} below {_fmt(rule.warning, rule.unit)} "
            f"for {len(window)} consecutive samples"
        )
    return Decision(
        kind=EventKind.RECOVERED,
        incident_type=rule.incident_type,
        severity=severity,
        at=window[0].ts,
        started_at=window[0].ts,
        threshold=_threshold(rule, severity),
        peak_value=peak,
        summary=summary,
        evidence=_evidence(rule, window),
    )


def _threshold(rule: Rule, severity: Severity) -> float:
    if severity is Severity.WARNING and rule.warning is not None:
        return rule.warning
    return rule.critical


def _breach_summary(
    rule: Rule, severity: Severity, threshold: float, peak: float, run_length: int
) -> str:
    if rule.incident_type is IncidentType.SERVICE_DOWN:
        return f"service down for {run_length} consecutive samples"
    return (
        f"{rule.label} >= {_fmt(threshold, rule.unit)} ({severity.value}) "
        f"for {run_length} consecutive samples, peak {_fmt(peak, rule.unit)}"
    )


def _fmt(value: float | None, unit: str) -> str:
    text = f"{value:g}"
    return f"{text} {unit}" if unit else text


def _evidence(rule: Rule, samples: Sequence[Sample]) -> list[dict[str, Any]]:
    return [{"ts": s.ts.isoformat(), "value": rule.value(s), "up": s.up} for s in samples]
