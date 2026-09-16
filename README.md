# Aurik Assessment — Industrial Equipment Monitoring Backend

Backend service for an industrial equipment monitoring platform. It ingests machine
event/sensor/alert/inspection/maintenance data from three vendors with inconsistent
schemas, normalizes it into a canonical internal model, processes it asynchronously,
and exposes a derived machine-level "attention" view plus plant/line summaries via
backend APIs.

Full requirements: [`Aurik_Technologies_Founding_Tech_Lead_Assessment_Candidate_Brief.md`](Aurik_Technologies_Founding_Tech_Lead_Assessment_Candidate_Brief.md)
Build plan and phase-by-phase log: [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)
Design rationale: [`DESIGN_NOTE.md`](DESIGN_NOTE.md)

## Stack

Python (FastAPI) + PostgreSQL + Redis/RQ (background worker) + Docker Compose.

## Architecture

```
                 ┌─────────────┐
 Vendor payload  │             │  202 Accepted (batch_id)
 ───────────────▶│  Ingestion  ├───────────────────────────▶ caller
  (3 vendor      │  (FastAPI)  │
   formats)      └──────┬──────┘
                         │ stores raw_batches / raw_events (status=pending)
                         │ enqueues normalize_batch(batch_id)
                         ▼
                 ┌─────────────┐
                 │    Redis    │◀────────────────────┐
                 │   (queue)   │                      │ enqueues
                 └──────┬──────┘                      │ recompute_machine_state
                         │ dequeues                    │
                         ▼                             │
                 ┌─────────────┐   NormalizedEvent /   │
                 │  RQ worker  ├──────────────────────┘
                 │             │   DeadLetterEvent
                 └──────┬──────┘
                         │ reads asset_reference / normalized_events
                         ▼
                 ┌─────────────┐
                 │  Derivation │  writes machine_state
                 │ rule engine │  (derived_status, attention_level,
                 └──────┬──────┘   reason_codes, processing_status)
                         │
                         ▼
                 ┌─────────────┐
                 │  Postgres   │◀─── read by ───┐
                 └─────────────┘                │
                                          ┌──────┴──────┐
                                          │ Output APIs │  status / machine view /
                                          │  (FastAPI)  │  plant+line summary
                                          └─────────────┘
```

Ingestion and querying happen synchronously in the `api` service; normalization and
derivation happen asynchronously in the `worker` service via Redis/RQ. See
`DESIGN_NOTE.md` for why each piece is shaped the way it is.

## Project layout

```
app/
  api/            # HTTP routers + response schemas (ingest, status, machines, summary)
  ingestion/      # per-vendor request schemas, auth, dedupe/raw-storage service
  normalization/  # per-vendor mappers, timestamp parsing, machine resolution
  processing/     # RQ job definitions + queue connection
  derivation/     # deterministic rule engine + machine_state materialization
  models/         # SQLAlchemy models (reference, raw, normalized, machine_state, dead_letter)
  db/             # DB session/engine setup
  config.py       # settings (env-driven)
  main.py         # FastAPI app entrypoint, router wiring
migrations/       # Alembic migrations (schema source of truth)
scripts/
  seed_reference_data.py   # loads asset_reference.csv / line_reference.csv
  normalize_pending.py     # manual trigger for normalization (debugging aid)
tests/            # pytest suite (unit + integration), see "Running tests"
Aurik_Tech_Lead_Assessment_Assets/   # provided reference data & vendor samples
docker-compose.yml
Dockerfile
```

## Running locally

Requires Docker + Docker Compose.

```
docker compose up -d --build
```

This starts, in dependency order:
- `postgres` — database
- `redis` — job queue backend
- `migrate` — one-shot job running `alembic upgrade head` (creates the schema)
- `seed` — one-shot job that loads `asset_reference.csv` / `line_reference.csv`
  into the database (safe to re-run; upserts by primary key)
- `api` — FastAPI app on `http://localhost:8000`
- `worker` — RQ background worker that normalizes batches and recomputes machine state

Check it's up:

```
curl http://localhost:8000/health
# {"status":"ok"}
```

Interactive API docs (Swagger UI, auto-generated from the code): `http://localhost:8000/docs`

Stop everything:

```
docker compose down
```

**Note:** the image is built from a `COPY . .` step with no bind mounts (see
"Known issues" below), so after changing code you need to rebuild before
re-running: `docker compose build api worker`.

## API overview

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/v1/ingest/pulseforge` | Ingest a PulseForge batch (header `X-Vendor-Key`) |
| `POST` | `/v1/ingest/thermexwatch` | Ingest a ThermexWatch batch (header `X-Vendor-Key`) |
| `POST` | `/v1/ingest/maintaflow` | Ingest a MaintaFlow batch (header `X-Vendor-Key`) |
| `GET` | `/v1/ingest/status/{batch_id}` | Per-batch processing status + dead-letter reasons |
| `GET` | `/v1/machines/{machine_id}` | Machine-level derived attention view |
| `GET` | `/v1/machines?plant_id=&line_id=&status=` | Filtered list of machine views |
| `GET` | `/v1/plants/{plant_id}/summary` | Plant-level status counts, critical machines, per-line breakdown |
| `GET` | `/v1/lines/{line_id}/summary` | Line-level status counts and critical machines |

Full request/response shapes: see `/docs` (Swagger UI) or `/openapi.json` once the
stack is running — this is the API contract for this submission (see Phase 6 of
`IMPLEMENTATION_PLAN.md` for the reasoning behind each endpoint).

Vendor API keys for local testing (see `.env.example` / `docker-compose.yml`):
`dev-pulseforge-key`, `dev-thermexwatch-key`, `dev-maintaflow-key`.

### Example

```bash
curl -X POST http://localhost:8000/v1/ingest/pulseforge \
  -H "Content-Type: application/json" \
  -H "X-Vendor-Key: dev-pulseforge-key" \
  -d @Aurik_Tech_Lead_Assessment_Assets/vendor_api_samples/pulseforge_sample.json
# {"batch_id": "...", "vendor": "pulseforge", "total_records": 2, "accepted": 2, ...}

curl http://localhost:8000/v1/ingest/status/<batch_id>
curl http://localhost:8000/v1/machines/EQ-001
curl http://localhost:8000/v1/plants/PLANT_01/summary
```

The worker processes the batch asynchronously; allow a second or two between the
ingest call and checking machine/plant views.

## Running tests

```
docker compose run --rm api pytest -q
```

49 tests: unit tests for the per-vendor normalizers and the rule engine (synthetic
inputs), plus integration tests that exercise real DB flows (ingest → normalize →
derive → API) using the provided fixture files in
`Aurik_Tech_Lead_Assessment_Assets/vendor_api_samples/` directly as test data —
`happy_path.json`, `malformed.json`, `duplicates.json`, `conflicting_updates.json`,
`out_of_order.json`, and `retry_cases.json` each map to specific test cases.

## Configuration

Copy `.env.example` to `.env` to override defaults (DB/Redis URLs, vendor API keys)
for local (non-Docker) runs. The Docker Compose services set their own environment
variables directly in `docker-compose.yml`.

## Assumptions & trade-offs

See `DESIGN_NOTE.md` for the full reasoning. Highlights:

- **Reference data is ground truth for plant/line**: vendor-supplied plant/line
  fields are ignored in favor of `asset_reference.csv`/`line_reference.csv`, since
  vendor conventions for line naming are inconsistent (e.g. ThermexWatch's bare-letter
  `productionLine`).
- **Vibration units are not cross-converted**: PulseForge's `vibration_mm_s`
  (velocity) and ThermexWatch's `vibration_g` (acceleration) are different physical
  quantities; converting requires frequency data we don't have, so they're kept
  distinct and only ThermexWatch's own vendor-reported severity can escalate a
  g-unit reading.
- **Staleness uses the dataset's own clock**, not wall-clock time — the sample data
  is a fixed historical batch, so "now" is defined as the latest `event_time_utc`
  seen anywhere in the data.
- **`partial` processing status was scoped out**: linking a dead-lettered record
  back to a specific machine would need per-vendor extraction logic on top of the
  generic dead-letter path; not worth the complexity here.
- **Per-vendor API keys, not OAuth/mTLS**: adequate for this assessment; a real
  deployment would want per-vendor credentials issued/rotated through a proper
  secrets system.

## Limitations / what's next for production

- **No pagination** on `/v1/machines` — fine at 8 machines, would need
  cursor/offset pagination at real scale.
- **No auth on the read APIs** (`/v1/machines`, `/v1/plants/*`, `/v1/lines/*`) —
  only the vendor ingestion endpoints are authenticated. A production deployment
  would put these behind the platform's own service-to-service auth.
- **Single Postgres, no read replica** — fine for this assessment's data volume;
  a production system with many vendors/machines would want to separate the
  write-heavy ingestion path from read-heavy dashboard queries.
- **No structured logging/metrics/tracing** — worth adding (e.g. per-batch
  processing latency, dead-letter rate per vendor) before running this for real.
- **`partial` processing status** (see above) — would need machine_id captured
  on `dead_letter_events` at ingestion time, before the vendor identifier is even
  known to be valid, to implement cleanly.
- **No backpressure/rate limiting** on ingestion endpoints.
- **Alembic migration was hand-written**, not autogenerated (see
  `IMPLEMENTATION_PLAN.md` Phase 1) — fine for one migration, but future schema
  changes should use `alembic revision --autogenerate` against a running DB.

## Known issues

- Docker Desktop/WSL2 on this Windows setup has a bind-mount bug for this drive
  layout (`mkdir /run/desktop/mnt/host/d: file exists`), so `docker-compose.yml`
  doesn't use bind mounts — the image is rebuilt on `--build` instead of
  live-reloading from the host. Rebuild after code changes (see "Running locally").

## AI usage disclosure

This project was built with Claude Code (Anthropic) as a pair-programming tool
across all phases: architecture/schema design, endpoint implementation, the
normalization and derivation rule logic, tests, and this documentation. All code
was reviewed, run against the real Docker Compose stack, and verified against the
provided fixture files (and via manual `curl` calls against the live API) at each
phase before moving to the next — see the phase-by-phase verification notes in
`IMPLEMENTATION_PLAN.md`. Design decisions (rule thresholds, conflict-resolution
strategy, what to explicitly scope out) were made and reviewed by the author, not
auto-accepted; the trade-offs listed above reflect judgment calls made during that
review, not unexamined AI output.
