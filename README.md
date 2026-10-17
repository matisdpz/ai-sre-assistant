# AI SRE Assistant

Simulates a small distributed system, monitors its metrics, detects incidents with
deterministic rules and helps an engineer investigate them.

> All telemetry is **simulated**. Nothing here monitors real infrastructure.

**Status:** Milestone 2. Backend skeleton, database schema, health checks and the
deterministic detection engine (`backend/app/detection.py`) are in place. Detection is not
yet wired to an ingest endpoint.

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
  app/            FastAPI application (config, logging, db, models, api/)
  migrations/     Alembic migrations
  tests/          unit/ (no database) and integration/ (PostgreSQL)
docker/           PostgreSQL init script (creates sre_test)
docker-compose.yml
```
