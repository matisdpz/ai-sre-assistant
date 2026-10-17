import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from simulator.scenarios import Generator

logger = logging.getLogger(__name__)


class Sender(Protocol):
    def send(self, samples: list[dict[str, Any]]) -> dict[str, Any]: ...


def run(
    generator: Generator,
    sender: Sender,
    *,
    interval: float,
    backfill: int = 0,
    ticks: int | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Send one batch per tick, `interval` seconds apart. Returns the number of ticks sent.

    Tick timestamps are fixed in advance (start + i * interval), so they stay evenly
    spaced even if a send is slow or retried. With `backfill`, the first ticks lie in the
    past and are sent without waiting, which fills the dashboard with history at once.
    """
    start = now() - timedelta(seconds=interval * backfill)
    tick = 0
    while ticks is None or tick < ticks:
        ts = start + timedelta(seconds=interval * tick)
        wait = (ts - now()).total_seconds()
        if wait > 0:
            sleep(wait)

        result = sender.send(generator.samples(tick, ts))
        decisions = [f"{d['service_id']}:{d['type']}:{d['kind']}" for d in result["decisions"]]
        logger.info(
            "tick %d sent (stored=%d duplicates=%d)%s",
            tick,
            result["stored"],
            result["duplicates"],
            f" decisions={decisions}" if decisions else "",
        )
        tick += 1
    return tick
