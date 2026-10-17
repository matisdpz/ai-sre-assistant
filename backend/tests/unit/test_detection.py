from datetime import UTC, datetime, timedelta

import pytest

from app.detection import (
    RULES,
    ActiveIncident,
    Rule,
    Sample,
    evaluate,
    evaluate_all,
    level,
)
from app.models import EventKind, IncidentType, Severity

T0 = datetime(2026, 1, 1, tzinfo=UTC)
RULE = {rule.incident_type: rule for rule in RULES}
ERRORS = RULE[IncidentType.HIGH_ERROR_RATE]
CPU = RULE[IncidentType.HIGH_CPU]
LATENCY = RULE[IncidentType.HIGH_LATENCY]
DOWN = RULE[IncidentType.SERVICE_DOWN]

OPEN_WARNING = ActiveIncident(Severity.WARNING, recovered=False)
OPEN_CRITICAL = ActiveIncident(Severity.CRITICAL, recovered=False)


def sample(i: int, **overrides: float | bool) -> Sample:
    """A healthy sample at T0 + i * 10 s, with some metrics overridden."""
    values: dict = {"error_rate": 1.0, "latency_p95_ms": 100.0, "cpu_pct": 30.0, "up": True}
    values.update(overrides)
    return Sample(ts=T0 + timedelta(seconds=10 * i), **values)


def errors(*rates: float) -> list[Sample]:
    return [sample(i, error_rate=rate) for i, rate in enumerate(rates)]


# --- single-sample levels -------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "metric", "value", "expected"),
    [
        (ERRORS, "error_rate", 4.99, None),
        (ERRORS, "error_rate", 5.0, Severity.WARNING),  # thresholds use >=
        (ERRORS, "error_rate", 9.99, Severity.WARNING),
        (ERRORS, "error_rate", 10.0, Severity.CRITICAL),
        (LATENCY, "latency_p95_ms", 500.0, Severity.WARNING),
        (LATENCY, "latency_p95_ms", 1000.0, Severity.CRITICAL),
        (CPU, "cpu_pct", 84.9, None),
        (CPU, "cpu_pct", 85.0, Severity.WARNING),
        (CPU, "cpu_pct", 95.0, Severity.CRITICAL),
        (DOWN, "up", True, None),
        (DOWN, "up", False, Severity.CRITICAL),
    ],
)
def test_level_boundaries(rule: Rule, metric: str, value: float, expected: Severity) -> None:
    assert level(rule, sample(0, **{metric: value})) is expected


def test_rule_table_matches_specification() -> None:
    spec = {
        IncidentType.HIGH_ERROR_RATE: (5.0, 10.0, 3, 3),
        IncidentType.HIGH_LATENCY: (500.0, 1000.0, 3, 3),
        IncidentType.HIGH_CPU: (85.0, 95.0, 5, 3),
        IncidentType.SERVICE_DOWN: (None, 1.0, 2, 2),
    }
    actual = {
        r.incident_type: (r.warning, r.critical, r.breach_samples, r.recovery_samples)
        for r in RULES
    }
    assert actual == spec


# --- detection ------------------------------------------------------------------------


def test_no_samples_no_decision() -> None:
    assert evaluate(ERRORS, [], None) is None


def test_fewer_than_n_breaching_samples_does_not_detect() -> None:
    assert evaluate(ERRORS, errors(6, 6), None) is None


def test_n_breaching_samples_detect_a_warning() -> None:
    decision = evaluate(ERRORS, errors(1, 6, 7, 8), None)

    assert decision is not None
    assert decision.kind is EventKind.DETECTED
    assert decision.severity is Severity.WARNING
    assert decision.threshold == 5.0
    assert decision.peak_value == 8.0
    assert decision.started_at == T0 + timedelta(seconds=10)  # first breaching sample
    assert decision.at == T0 + timedelta(seconds=30)  # latest sample, not the wall clock
    assert [e["value"] for e in decision.evidence] == [6, 7, 8]


def test_interrupted_breach_does_not_detect() -> None:
    assert evaluate(ERRORS, errors(6, 7, 1, 8, 9), None) is None


def test_single_critical_spike_inside_window_gives_warning_only() -> None:
    decision = evaluate(ERRORS, errors(6, 50, 6), None)
    assert decision is not None
    assert decision.severity is Severity.WARNING
    assert decision.peak_value == 50


def test_n_critical_samples_detect_a_critical() -> None:
    decision = evaluate(ERRORS, errors(12, 15, 11), None)
    assert decision is not None
    assert decision.severity is Severity.CRITICAL
    assert decision.threshold == 10.0


def test_started_at_covers_the_whole_breaching_run() -> None:
    decision = evaluate(ERRORS, errors(1, 6, 6, 6, 6, 6), None)
    assert decision is not None
    assert decision.started_at == T0 + timedelta(seconds=10)
    assert len(decision.evidence) == 3  # evidence is the N-sample window


def test_cpu_needs_five_samples() -> None:
    four = [sample(i, cpu_pct=90) for i in range(4)]
    five = [sample(i, cpu_pct=90) for i in range(5)]
    assert evaluate(CPU, four, None) is None
    assert evaluate(CPU, five, None) is not None


def test_service_down_after_two_samples() -> None:
    samples = [sample(0), sample(1, up=False), sample(2, up=False)]
    decision = evaluate(DOWN, samples, None)
    assert decision is not None
    assert decision.kind is EventKind.DETECTED
    assert decision.severity is Severity.CRITICAL
    assert decision.summary == "service down for 2 consecutive samples"


def test_metric_rules_ignore_samples_from_a_down_service() -> None:
    # The down samples report 0 % errors; they must neither break the run nor recover it.
    samples = [
        sample(0, error_rate=6),
        sample(1, error_rate=0, up=False),
        sample(2, error_rate=7),
        sample(3, error_rate=8),
    ]
    assert evaluate(ERRORS, samples, None) is not None

    down_only = [sample(i, error_rate=0, up=False) for i in range(5)]
    assert evaluate(ERRORS, down_only, OPEN_WARNING) is None


# --- escalation -----------------------------------------------------------------------


def test_warning_escalates_after_n_critical_samples() -> None:
    decision = evaluate(ERRORS, errors(6, 12, 13, 14), OPEN_WARNING)
    assert decision is not None
    assert decision.kind is EventKind.ESCALATED
    assert decision.severity is Severity.CRITICAL
    assert decision.started_at == T0  # the run started at the first warning sample


def test_no_escalation_without_n_critical_samples() -> None:
    assert evaluate(ERRORS, errors(6, 12, 13), OPEN_WARNING) is None  # only 2 critical
    assert evaluate(ERRORS, errors(12, 6, 13), OPEN_WARNING) is None  # not consecutive


def test_severity_never_downgrades() -> None:
    assert evaluate(ERRORS, errors(6, 6, 6), OPEN_CRITICAL) is None


def test_ongoing_incident_at_same_severity_is_unchanged() -> None:
    assert evaluate(ERRORS, errors(6, 7, 8), OPEN_WARNING) is None


# --- recovery and retrigger -----------------------------------------------------------


def test_m_healthy_samples_mark_recovery() -> None:
    decision = evaluate(ERRORS, errors(8, 1, 2, 3), OPEN_CRITICAL)
    assert decision is not None
    assert decision.kind is EventKind.RECOVERED
    assert decision.severity is Severity.CRITICAL  # recovery keeps the reached severity
    assert decision.at == T0 + timedelta(seconds=10)  # first healthy sample


def test_fewer_than_m_healthy_samples_do_not_recover() -> None:
    assert evaluate(ERRORS, errors(8, 1, 2), OPEN_WARNING) is None


def test_warning_level_sample_is_not_healthy() -> None:
    assert evaluate(ERRORS, errors(1, 1, 5), OPEN_CRITICAL) is None


def test_service_up_again_recovers_after_two_samples() -> None:
    samples = [sample(0, up=False), sample(1), sample(2)]
    decision = evaluate(DOWN, samples, OPEN_CRITICAL)
    assert decision is not None
    assert decision.kind is EventKind.RECOVERED


def test_already_recovered_incident_is_not_recovered_again() -> None:
    recovered = ActiveIncident(Severity.WARNING, recovered=True)
    assert evaluate(ERRORS, errors(1, 1, 1), recovered) is None


def test_breach_after_recovery_retriggers_without_downgrade() -> None:
    recovered = ActiveIncident(Severity.CRITICAL, recovered=True)
    decision = evaluate(ERRORS, errors(1, 6, 6, 6), recovered)
    assert decision is not None
    assert decision.kind is EventKind.RETRIGGERED
    assert decision.severity is Severity.CRITICAL


def test_retrigger_can_escalate() -> None:
    recovered = ActiveIncident(Severity.WARNING, recovered=True)
    decision = evaluate(ERRORS, errors(20, 20, 20), recovered)
    assert decision is not None
    assert decision.severity is Severity.CRITICAL


# --- input validation and evaluate_all ------------------------------------------------


@pytest.mark.parametrize("order", [[1, 0, 2], [0, 1, 1]])
def test_unsorted_or_duplicate_timestamps_are_rejected(order: list[int]) -> None:
    samples = [sample(i) for i in order]
    with pytest.raises(ValueError, match="sorted"):
        evaluate(ERRORS, samples, None)


def test_evaluate_all_reports_each_rule_independently() -> None:
    samples = [sample(i, error_rate=12, latency_p95_ms=600) for i in range(3)]
    active = {IncidentType.HIGH_LATENCY: OPEN_WARNING}

    decisions = evaluate_all(samples, active)

    by_type = {d.incident_type: d for d in decisions}
    assert set(by_type) == {IncidentType.HIGH_ERROR_RATE}  # latency incident already open
    assert by_type[IncidentType.HIGH_ERROR_RATE].severity is Severity.CRITICAL


def test_evaluation_is_deterministic() -> None:
    samples = errors(1, 6, 12, 13)
    assert evaluate(ERRORS, samples, None) == evaluate(ERRORS, samples, None)
