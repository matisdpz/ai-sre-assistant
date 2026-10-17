# AI SRE Assistant

Simulates a small distributed system, monitors its metrics, detects incidents with
deterministic rules and helps an engineer investigate them.

> All telemetry is **simulated**. Nothing here monitors real infrastructure.

**Status:** Milestone 1. Backend skeleton, database schema and health checks are in place.

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

## Project layout

```
backend/
  app/            FastAPI application (config, logging, db, models, api/)
  migrations/     Alembic migrations
  tests/          unit/ (no database) and integration/ (PostgreSQL)
docker/           PostgreSQL init script (creates sre_test)
docker-compose.yml
```
