import logging
import time
from collections.abc import Callable
from typing import Any

import httpx2

logger = logging.getLogger(__name__)
INGEST_PATH = "/api/v1/ingest/metrics"


class FatalIngestError(Exception):
    """Retrying cannot help (bad token or rejected payload): stop the simulator."""


class IngestClient:
    """Sends batches to the ingest API, retrying transient failures.

    Retrying is safe because ingest is idempotent: a batch that was stored but whose
    response got lost is counted as duplicates the second time, not stored twice.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: httpx2.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_backoff: float = 30.0,
        max_attempts: int | None = None,  # None: retry until the API is back
    ) -> None:
        self._http = httpx2.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
            transport=transport,
        )
        self._sleep = sleep
        self._max_backoff = max_backoff
        self._max_attempts = max_attempts

    def send(self, samples: list[dict[str, Any]]) -> dict[str, Any]:
        delay = 1.0
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._http.post(INGEST_PATH, json={"samples": samples})
            except httpx2.TransportError as exc:
                logger.warning("ingest API unreachable (%s), retrying in %.0f s", exc, delay)
            else:
                if response.status_code == 200:
                    return response.json()
                if response.status_code in (401, 403):
                    raise FatalIngestError("ingest token rejected: check INGEST_TOKEN")
                if 400 <= response.status_code < 500:
                    raise FatalIngestError(
                        f"payload rejected ({response.status_code}): {response.text[:500]}"
                    )
                logger.warning(
                    "ingest API error %s, retrying in %.0f s", response.status_code, delay
                )

            if self._max_attempts is not None and attempt >= self._max_attempts:
                raise ConnectionError(f"ingest failed after {attempt} attempts")
            self._sleep(delay)
            delay = min(delay * 2, self._max_backoff)

    def close(self) -> None:
        self._http.close()
