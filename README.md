# AI SRE Assistant

Simulates a small distributed system, monitors its metrics, detects incidents with
deterministic rules and helps an engineer investigate them.

> All telemetry is **simulated**. Nothing here monitors real infrastructure.

**Status:** Milestone 5. A simulator generates fake metrics and failure scenarios, the
backend detects incidents with deterministic rules, and a React dashboard shows services,
metrics and incidents, which a person can acknowledge and resolve. Everything runs with one
Docker Compose command.

## Quick start (Docker)

Requirements: Docker with Docker Compose.

```bash
cp .env.example .env     # then replace every "change-me" value (INGEST_TOKEN: 16+ chars)
docker compose up -d --build
```

- Dashboard: <http://localhost:8080>
- API docs: <http://localhost:8000/docs>

Compose starts PostgreSQL, runs the migrations once (`migrate` job), then the API, the
simulator and the dashboard (nginx). The default `demo` scenario produces an error spike, a
database outage with a cascade and a CPU saturation, every 15 minutes; the first incident
appears after about 1.5 minutes. To run another scenario:
`SIMULATOR_SCENARIO=db-outage docker compose up -d simulator`.

```bash
docker compose logs -f simulator   # samples sent and the incidents they trigger
docker compose down                # stop (data kept); add -v to delete the database
```

## Architecture

```
simulator ──POST /api/v1/ingest/metrics (bearer token)──▶ API (FastAPI)
                                                          │  route → incident_manager
                                                          │        → detection (pure rules)
                                                          │        → repository (SQL)
browser ──▶ nginx (dashboard + /api proxy) ──────────────▶│
                                                          ▼
                                                     PostgreSQL 17
```

- The **simulator** is a separate process; it only knows the HTTP API.
- **Detection** (`backend/app/detection.py`) is pure: no database, no I/O, no wall clock.
  The incident manager feeds it samples and persists its decisions in one transaction.
- The **dashboard** polls the API every 5 s through nginx (same origin, no CORS).

## Simulator

`backend/simulator/` never imports the backend code (a test checks it). Samples come from
per-service baselines with bounded noise, so a healthy service never crosses a threshold,
and the same `--seed` always produces the same samples.

| Scenario | What happens |
|---|---|
| `normal` | Everything healthy (no incident, checked by a test over 2000 ticks) |
| `error-spike` | payment-service at about 12 % errors |
| `latency` | payment-service p95 at about 1.2 s |
| `cpu-saturation` | api-gateway CPU at about 97 % |
| `db-outage` | database-service down; payment-service slows down and fails in cascade |
| `demo` | The above in turn, every 15 minutes |

Transient API failures (connection refused, 5xx) are retried with exponential backoff,
which is safe because ingest is idempotent. A rejected token or payload stops it.

```bash
cd backend
.venv/bin/python -m simulator --scenario db-outage --interval 2   # faster ticks
.venv/bin/python -m simulator --help
```

## Local development

Requirements: Python 3.12, Node 22 and npm 11 or later (npm 10 crashes while resolving
vitest's peer dependencies; with npm 10, use `npx npm@11.21.0 install`), Docker for
PostgreSQL.

```bash
cp .env.example .env              # then replace every "change-me" value
docker compose up -d db           # PostgreSQL on 127.0.0.1:5432, plus the sre_test database

cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head    # create tables and seed the three services
.venv/bin/uvicorn --factory app.main:create_app --reload
.venv/bin/python -m simulator     # in another terminal

cd frontend
npm install
npm run dev                       # http://localhost:5173, /api proxied to :8000
```

- Liveness: <http://localhost:8000/health/live> (the process is running)
- Readiness: <http://localhost:8000/health/ready> (the database answers; 503 otherwise)

## Checks

```bash
cd backend
.venv/bin/pytest                         # unit + integration tests
.venv/bin/pytest -m "not integration"    # unit tests only, no database needed
.venv/bin/ruff check . && .venv/bin/ruff format --check .

cd frontend
npm test                                 # vitest
npm run typecheck
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
| `SIMULATOR_API_URL` | Where the simulator sends samples (default `http://localhost:8000`) |
| `SIMULATOR_SCENARIO` | Compose only: scenario of the simulator container (default `demo`) |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | PostgreSQL container |

Environment variables override values from `.env`. Logs are JSON lines on stdout and
never include the database password. In Compose, the migration job only receives
`DATABASE_URL`, and the simulator only `INGEST_TOKEN`.

## Ingesting metrics

`POST /api/v1/ingest/metrics` takes a batch of simulated samples (1 to 500). It requires
`Authorization: Bearer $INGEST_TOKEN`. nginx does not expose it: only the simulator, on the
Compose network or locally, calls it.

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

## Incidents API

| Method and path | Purpose |
|---|---|
| `GET /api/v1/services` | Services with their number of unresolved incidents |
| `GET /api/v1/services/{id}/metrics?since=&limit=` | Simulated samples, oldest first (default: last 360) |
| `GET /api/v1/incidents?status=&service_id=&limit=&offset=` | Incidents, newest first |
| `GET /api/v1/incidents/{id}` | One incident with its evidence and timeline |
| `POST /api/v1/incidents/{id}/acknowledge` | `open → acknowledged`, optional `{"note": "..."}` |
| `POST /api/v1/incidents/{id}/resolve` | `open` or `acknowledged → resolved` (final) |
| `GET /api/v1/rules` | Detection thresholds (the dashboard draws them on the charts) |

An invalid transition (e.g. acknowledging twice, or touching a resolved incident) returns
**409** and records nothing. Detection keeps updating an acknowledged incident (escalation,
recovery); only resolution closes it, and a recurrence opens a new incident.

The read and status endpoints have no authentication yet: the project runs locally and
every port is bound to `127.0.0.1`.

## Detection rules

Thresholds use `>=`.

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
  app/            FastAPI application: api/ (routes), incident_manager.py (workflows),
                  detection.py (pure rules), repository.py (SQL), models, schemas
  simulator/      Separate process generating simulated metrics (talks HTTP only)
  migrations/     Alembic migrations (written by hand)
  tests/          unit/ (no database) and integration/ (PostgreSQL)
  Dockerfile      One image for the API, the migration job and the simulator
frontend/
  src/            React + TypeScript dashboard (pages/, components/, api.ts)
  Dockerfile      Node build stage, then nginx serving the files and proxying /api
docker/           PostgreSQL init script (creates sre_test)
docker-compose.yml
```
