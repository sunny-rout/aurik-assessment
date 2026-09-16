# Aurik Assessment — Industrial Equipment Monitoring Backend

Backend service for an industrial equipment monitoring platform. It ingests machine
event/sensor/alert/inspection/maintenance data from multiple vendors with inconsistent
schemas, normalizes it into a canonical internal model, processes it asynchronously,
and exposes a derived machine-level operational (attention) view via backend APIs.


## Stack

Python (FastAPI) + PostgreSQL + Redis/RQ (background worker) + Docker Compose.

## Project layout

```
app/
  api/            # HTTP routers (not yet implemented)
  ingestion/      # per-vendor request handlers (not yet implemented)
  normalization/  # per-vendor mappers + validators (not yet implemented)
  processing/     # RQ background jobs (not yet implemented)
  derivation/     # machine attention rule engine (not yet implemented)
  models/         # SQLAlchemy models (reference data models only so far)
  db/             # DB session/engine setup
  config.py       # settings (env-driven)
  main.py         # FastAPI app entrypoint (/health only so far)
scripts/
  seed_reference_data.py   # loads asset_reference.csv / line_reference.csv
tests/
  test_health.py
Aurik_Tech_Lead_Assessment_Assets/   # provided reference data & vendor samples
docker-compose.yml
Dockerfile
```

## Running locally

Requires Docker + Docker Compose.

```
docker compose up -d --build
```

This starts:
- `postgres` — database
- `redis` — job queue backend
- `seed` — one-shot job that loads `asset_reference.csv` / `line_reference.csv`
  into the database (safe to re-run; upserts by primary key)
- `api` — FastAPI app on `http://localhost:8000`
- `worker` — RQ background worker (idle until Phase 4 wires up jobs)

Check it's up:

```
curl http://localhost:8000/health
# {"status":"ok"}
```

Stop everything:

```
docker compose down
```

## Running tests

```
docker compose run --rm api pytest -q
```

## Configuration

Copy `.env.example` to `.env` to override defaults (DB/Redis URLs, vendor API keys)
for local (non-Docker) runs. The Docker Compose services set their own environment
variables directly.

## Notes

- Bind mounts were intentionally left out of `docker-compose.yml` (hit a Docker
  Desktop/WSL2 path bug on Windows for this drive layout); the image is rebuilt
  on `docker compose up --build` instead of live-reloading from the host.

