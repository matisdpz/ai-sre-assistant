"""Run the metrics simulator: python -m simulator --scenario demo

All telemetry it produces is simulated.
"""

import argparse
import logging
import signal
import sys
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from simulator.client import FatalIngestError, IngestClient
from simulator.runner import run
from simulator.scenarios import SCENARIOS, Generator

logger = logging.getLogger("simulator")


class SimulatorSettings(BaseSettings):
    # Same repository-root .env as the backend locally; real env variables in containers.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore"
    )

    ingest_token: SecretStr
    simulator_api_url: str = "http://localhost:8000"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="simulator", description=__doc__)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="demo")
    parser.add_argument("--seed", type=int, default=42, help="same seed, same samples")
    parser.add_argument("--interval", type=float, default=10.0, help="seconds between ticks")
    parser.add_argument(
        "--backfill", type=int, default=0, help="ticks of past history to send first"
    )
    parser.add_argument("--ticks", type=int, default=None, help="stop after this many ticks")
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)  # one line per request is noise
    # Docker stops containers with SIGTERM: exit cleanly instead of being killed.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    settings = SimulatorSettings()
    scenario = SCENARIOS[args.scenario]
    logger.info("scenario %r: %s (simulated telemetry)", args.scenario, scenario.description)

    client = IngestClient(settings.simulator_api_url, settings.ingest_token.get_secret_value())
    try:
        run(
            Generator(scenario, args.seed),
            client,
            interval=args.interval,
            backfill=args.backfill,
            ticks=args.ticks,
        )
    except FatalIngestError as exc:
        logger.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logger.info("stopped")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
