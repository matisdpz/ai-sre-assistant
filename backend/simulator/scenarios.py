"""Simulated services and fault scenarios. Everything here is fake telemetry.

The simulator is a separate process: it never imports the backend (`app`) and only talks
to it over HTTP, like a real metrics agent would.
"""

import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Baseline:
    """Healthy behaviour of a service: comfortably below every detection threshold."""

    request_rate: float  # requests per second
    error_rate: float  # percent
    latency_p95_ms: float
    cpu_pct: float
    mem_pct: float


BASELINES: dict[str, Baseline] = {
    "api-gateway": Baseline(220.0, 0.5, 120.0, 35.0, 45.0),
    "payment-service": Baseline(80.0, 0.8, 180.0, 40.0, 55.0),
    "database-service": Baseline(150.0, 0.2, 25.0, 30.0, 65.0),
}

# Uniform noise, as a fraction of the value. Bounded (not Gaussian) so a healthy service
# provably never crosses a threshold by chance.
HEALTHY_NOISE = 0.08
FAULT_NOISE = 0.03


@dataclass(frozen=True)
class Fault:
    service_id: str
    start: int  # first tick of the fault, within the scenario cycle
    duration: int  # in ticks
    metrics: Mapping[str, float] = field(default_factory=dict)  # replaced baseline values
    up: bool = True  # False: the service is down

    def active(self, tick_in_cycle: int) -> bool:
        return self.start <= tick_in_cycle < self.start + self.duration


@dataclass(frozen=True)
class Scenario:
    description: str
    cycle: int  # ticks; faults repeat every cycle so a long-running demo keeps producing them
    faults: tuple[Fault, ...] = ()


_ERROR_SPIKE = Fault("payment-service", start=6, duration=12, metrics={"error_rate": 12.0})
_LATENCY = Fault("payment-service", start=6, duration=10, metrics={"latency_p95_ms": 1200.0})
_CPU = Fault("api-gateway", start=6, duration=10, metrics={"cpu_pct": 97.0})
_DB_DOWN = Fault("database-service", start=6, duration=6, up=False)
# Cascade: the payment service depends on the database, so it slows down and fails too.
_DB_CASCADE = Fault(
    "payment-service",
    start=6,
    duration=8,
    metrics={"latency_p95_ms": 1300.0, "error_rate": 15.0},
)


def _shift(fault: Fault, start: int) -> Fault:
    return Fault(fault.service_id, start, fault.duration, fault.metrics, fault.up)


SCENARIOS: dict[str, Scenario] = {
    "normal": Scenario("All services healthy.", cycle=1),
    "error-spike": Scenario("payment-service returns 12 % errors.", 60, (_ERROR_SPIKE,)),
    "latency": Scenario("payment-service p95 latency reaches 1.2 s.", 60, (_LATENCY,)),
    "cpu-saturation": Scenario("api-gateway CPU at about 97 %.", 60, (_CPU,)),
    "db-outage": Scenario(
        "database-service goes down; payment-service degrades in cascade.",
        60,
        (_DB_DOWN, _DB_CASCADE),
    ),
    "demo": Scenario(
        "Error spike, then a database outage, then CPU saturation, every 15 minutes.",
        90,
        (
            _ERROR_SPIKE,
            _shift(_DB_DOWN, 36),
            _shift(_DB_CASCADE, 36),
            _shift(_CPU, 64),
        ),
    ),
}


class Generator:
    """Deterministic: the same scenario and seed always produce the same samples."""

    def __init__(self, scenario: Scenario, seed: int) -> None:
        self._scenario = scenario
        self._rng = random.Random(seed)

    def samples(self, tick: int, ts: datetime) -> list[dict[str, Any]]:
        """One sample per service for this tick, ready for the ingest API."""
        tick_in_cycle = tick % self._scenario.cycle
        faults = [f for f in self._scenario.faults if f.active(tick_in_cycle)]
        return [
            self._sample(
                service_id, baseline, [f for f in faults if f.service_id == service_id], ts
            )
            for service_id, baseline in sorted(BASELINES.items())
        ]

    def _sample(
        self, service_id: str, baseline: Baseline, faults: list[Fault], ts: datetime
    ) -> dict[str, Any]:
        sample: dict[str, Any] = {"service_id": service_id, "ts": ts.isoformat(), "up": True}
        if any(not f.up for f in faults):
            # A crashed service serves nothing; its numbers are meaningless zeros.
            metrics = dict.fromkeys(("request_rate", "error_rate", "latency_p95_ms"), 0.0)
            metrics |= {"cpu_pct": 0.0, "mem_pct": 0.0}
            return sample | metrics | {"up": False}

        overrides: dict[str, float] = {}
        for fault in faults:
            overrides |= fault.metrics
        for name, healthy in vars(baseline).items():
            value, noise = (
                (overrides[name], FAULT_NOISE) if name in overrides else (healthy, HEALTHY_NOISE)
            )
            value *= 1 + self._rng.uniform(-noise, noise)
            if name in ("error_rate", "cpu_pct", "mem_pct"):
                value = min(value, 100.0)
            sample[name] = round(max(value, 0.0), 2)
        return sample
