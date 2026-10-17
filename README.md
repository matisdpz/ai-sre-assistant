# AI SRE Assistant

Simulates a small distributed system, monitors its metrics, detects incidents with
deterministic rules and helps an engineer investigate them.

> All telemetry is **simulated**. Nothing here monitors real infrastructure.

**Status:** Milestone 3. Simulated metrics are ingested over HTTP, stored in PostgreSQL and
run through the deterministic detection engine, which opens, escalates and recovers
incidents. The incidents API and dashboard come next.

## Requirements

- Python 3.12
- Docker with Docker Compose (used to run PostgreSQL 17)

## Local setup

```bash
cp .env.example .env              # then replace every "change-me" value
docker compose up -d db           # PostgreSQL on 127.0.0.1:5432, plus the sre_test database

cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head    # create tables and seed the three services
.venv/bin/uvicorn --factory app.main:create_app --reload
```

- Liveness: <http://localhost:8000/health/live> (the process is running)
- Readiness: <http://localhost:8000/health/ready> (the database answers; 503 otherwise)
- API docs: <http://localhost:8000/docs>

## Ingesting metrics

`POST /api/v1/ingest/metrics` takes a batch of simulated samples (1 to 500). It requires
`Authorization: Bearer $INGEST_TOKEN`.

```bash
curl -X POST localhost:8000/api/v1/ingest/metrics \
  -H "Authorization: Bearer $INGEST_TOKEN" -H "Content-Type: application/json" \
  -d '{"samples": [{"service_id": "payment-service", "ts": "2026-01-01T12:00:00Z",
       "request_rate": 120, "error_rate": 7.5, "latency_p95_ms": 180,
       "cpu_pct": 40, "mem_pct": 55, "up": true}]}'
```

Response: `stored`, `duplicates` (same service and timestamp, ignored), `late` (older than
the latest stored sample: kept but not evaluated) and the incident `decisions` taken.

- One request is one transaction: the samples and their incidents are saved together or
  not at all.
- Requests for the same service are serialized by a row lock on the service, so two
  concurrent requests cannot open the same incident twice. The partial unique index
  `uq_incidents_active_service_type` is the last line of defence.
- Known services: `api-gateway`, `payment-service`, `database-service`. Unknown → 422.

## Checks

Run from `backend/`:

```bash
.venv/bin/pytest                  # unit + integration tests
.venv/bin/pytest -m "not integration"   # unit tests only, no database needed
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Integration tests use `TEST_DATABASE_URL`. They drop and recreate the schema, so they
refuse to run unless the database name ends with `_test`. Without that variable they are
skipped.

## Configuration

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://…` connection string (required) |
| `APP_ENV` | `development`, `test` or `production` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |
| `INGEST_TOKEN` | Shared secret for the ingest endpoint, at least 16 characters (required) |
| `TEST_DATABASE_URL` | Database used by integration tests (name must end with `_test`) |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | PostgreSQL container |

Environment variables override values from `.env`. Logs are JSON lines on stdout and
never include the database password.

## Detection rules

Pure functions in `backend/app/detection.py`: no database, no I/O, no wall clock (time comes
from sample timestamps). Thresholds use `>=`.

| Rule | Warning | Critical | Opens after N samples | Recovers after M samples |
|---|---|---|---|---|
| `high_error_rate` | 5 % | 10 % | 3 | 3 |
| `high_latency` (p95) | 500 ms | 1000 ms | 3 | 3 |
| `high_cpu` | 85 % | 95 % | 5 | 3 |
| `service_down` | - | `up = false` | 2 | 2 |

- Severity is the level held by **all** of the last N samples, so a single spike does not
  open a critical incident. A warning escalates to critical after N critical samples, and
  never downgrades.
- Recovery needs M consecutive healthy samples (below the warning threshold) and only sets
  `recovered_at`; a person resolves the incident. A new breach before resolution
  retriggers the same incident.
- Metric rules ignore samples from a down service (`service_down` covers that case).

## Project layout

```
backend/
  app/            FastAPI application: api/ (routes), incident_manager.py (ingest
                  workflow), detection.py (pure rules), repository.py (SQL), models
  migrations/     Alembic migrations
  tests/          unit/ (no database) and integration/ (PostgreSQL)
docker/           PostgreSQL init script (creates sre_test)
docker-compose.yml
```
