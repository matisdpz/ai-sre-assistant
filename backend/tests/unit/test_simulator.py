import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest

from app.detection import ActiveIncident, Sample, evaluate_all
from app.models import EventKind, IncidentType
from app.schemas import MetricBatchIn
from simulator.client import FatalIngestError, IngestClient
from simulator.runner import run
from simulator.scenarios import BASELINES, SCENARIOS, Generator

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def generate(scenario: str, ticks: int, seed: int = 1) -> list[list[dict[str, Any]]]:
    generator = Generator(SCENARIOS[scenario], seed)
    return [generator.samples(t, T0 + timedelta(seconds=10 * t)) for t in range(ticks)]


def replay(scenario: str, ticks: int) -> list[tuple[str, IncidentType, EventKind]]:
    """Feed a scenario through the real (pure) detection engine, tick by tick."""
    history: dict[str, list[Sample]] = defaultdict(list)
    active: dict[str, dict[IncidentType, ActiveIncident]] = defaultdict(dict)
    seen = []
    for batch in generate(scenario, ticks):
        for raw in batch:
            service = raw["service_id"]
            history[service].append(
                Sample(
                    ts=datetime.fromisoformat(raw["ts"]),
                    error_rate=raw["error_rate"],
                    latency_p95_ms=raw["latency_p95_ms"],
                    cpu_pct=raw["cpu_pct"],
                    up=raw["up"],
                )
            )
            for d in evaluate_all(history[service][-20:], active[service]):
                recovered = d.kind is EventKind.RECOVERED
                active[service][d.incident_type] = ActiveIncident(d.severity, recovered)
                seen.append((service, d.incident_type, d.kind))
    return seen


# --- generated data -------------------------------------------------------------------


def test_same_seed_same_samples() -> None:
    assert generate("demo", 50, seed=7) == generate("demo", 50, seed=7)
    assert generate("demo", 50, seed=7) != generate("demo", 50, seed=8)


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_every_batch_is_accepted_by_the_ingest_schema(scenario: str) -> None:
    for batch in generate(scenario, SCENARIOS[scenario].cycle + 5):
        MetricBatchIn.model_validate({"samples": batch})
        assert {s["service_id"] for s in batch} == set(BASELINES)


def test_normal_scenario_never_opens_an_incident() -> None:
    assert replay("normal", 2000) == []


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("error-spike", {("payment-service", IncidentType.HIGH_ERROR_RATE)}),
        ("latency", {("payment-service", IncidentType.HIGH_LATENCY)}),
        ("cpu-saturation", {("api-gateway", IncidentType.HIGH_CPU)}),
        (
            "db-outage",
            {
                ("database-service", IncidentType.SERVICE_DOWN),
                ("payment-service", IncidentType.HIGH_LATENCY),
                ("payment-service", IncidentType.HIGH_ERROR_RATE),
            },
        ),
    ],
)
def test_fault_scenarios_open_the_expected_incidents_then_recover(
    scenario: str, expected: set[tuple[str, IncidentType]]
) -> None:
    events = replay(scenario, SCENARIOS[scenario].cycle)  # one fault, then calm

    assert {(s, t) for s, t, kind in events if kind is EventKind.DETECTED} == expected
    assert {(s, t) for s, t, kind in events if kind is EventKind.RECOVERED} == expected


def test_demo_scenario_covers_every_rule() -> None:
    types = {
        t for _, t, kind in replay("demo", SCENARIOS["demo"].cycle) if kind is EventKind.DETECTED
    }
    assert types == set(IncidentType)


def test_error_spike_is_critical() -> None:
    # 12 % errors with 3 % noise always stays above the 10 % critical threshold.
    generator = Generator(SCENARIOS["error-spike"], seed=3)
    fault = SCENARIOS["error-spike"].faults[0]
    for tick in range(fault.start, fault.start + fault.duration):
        [payment] = [s for s in generator.samples(tick, T0) if s["service_id"] == "payment-service"]
        assert payment["error_rate"] >= 10


def test_down_service_reports_up_false() -> None:
    fault = SCENARIOS["db-outage"].faults[0]
    batch = generate("db-outage", fault.start + 1)[fault.start]
    [db] = [s for s in batch if s["service_id"] == "database-service"]
    assert db["up"] is False


# --- HTTP client ----------------------------------------------------------------------

OK_BODY = {"stored": 3, "duplicates": 0, "late": 0, "decisions": []}


def client_with(responses: list[Any], **kwargs: Any) -> tuple[IngestClient, list[float]]:
    """A client whose transport returns `responses` in order (an exception is raised)."""
    sleeps: list[float] = []
    queue = list(responses)

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["authorization"] == "Bearer secret-token-123456"
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    client = IngestClient(
        "http://api",
        "secret-token-123456",
        transport=httpx2.MockTransport(handler),
        sleep=sleeps.append,
        **kwargs,
    )
    return client, sleeps


def test_transient_failures_are_retried_with_exponential_backoff() -> None:
    client, sleeps = client_with(
        [
            httpx2.ConnectError("refused"),
            httpx2.Response(503),
            httpx2.Response(500),
            httpx2.Response(200, json=OK_BODY),
        ]
    )
    assert client.send([]) == OK_BODY
    assert sleeps == [1.0, 2.0, 4.0]


def test_backoff_is_capped() -> None:
    client, sleeps = client_with(
        [httpx2.Response(503)] * 6 + [httpx2.Response(200, json=OK_BODY)], max_backoff=5
    )
    client.send([])
    assert sleeps == [1.0, 2.0, 4.0, 5.0, 5.0, 5.0]


@pytest.mark.parametrize("status", [401, 403, 422])
def test_client_errors_are_fatal_not_retried(status: int) -> None:
    client, sleeps = client_with([httpx2.Response(status, text="nope")])
    with pytest.raises(FatalIngestError):
        client.send([])
    assert sleeps == []


def test_gives_up_after_max_attempts() -> None:
    client, _ = client_with([httpx2.Response(503)] * 3, max_attempts=3)
    with pytest.raises(ConnectionError, match="3 attempts"):
        client.send([])


# --- runner ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.current = start
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += timedelta(seconds=seconds)


class RecordingSender:
    def __init__(self) -> None:
        self.batches: list[list[dict[str, Any]]] = []

    def send(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        self.batches.append(samples)
        return OK_BODY


def test_runner_paces_ticks_and_backfills_without_waiting() -> None:
    clock, sender = FakeClock(T0), RecordingSender()

    sent = run(
        Generator(SCENARIOS["normal"], 1),
        sender,
        interval=10,
        backfill=3,
        ticks=5,
        now=clock.now,
        sleep=clock.sleep,
    )

    assert sent == 5
    timestamps = [datetime.fromisoformat(batch[0]["ts"]) for batch in sender.batches]
    assert timestamps == [T0 + timedelta(seconds=s) for s in (-30, -20, -10, 0, 10)]
    assert clock.sleeps == [10.0]  # past ticks go at once; only the future one waits


# --- isolation ------------------------------------------------------------------------


def test_simulator_does_not_import_the_backend() -> None:
    code = (
        "import sys, simulator.__main__; "
        "leaked = [m for m in sys.modules if m == 'app' or m.startswith('app.')]; "
        "assert not leaked, leaked"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
