# Implementation Plan — Industrial Equipment Monitoring Backend

## Branch

`feature/monitoring-backend`

All work happens on this branch off `main`, with one commit per completed phase (or more granular, but visible commit history is a deliverable — commit as you go, not one giant squash at the end).

## Stack

Python + FastAPI + PostgreSQL + Redis/RQ (background worker) + Docker Compose.

## Canonical Schema (target of normalization)

```
NormalizedEvent
- id, source_event_ref (vendor + native id), vendor
- machine_id, plant_id, line_id        (resolved via asset_reference.csv / line_reference.csv)
- event_time_utc
- category: vibration | temperature | power | sensor_health | inspection | maintenance | note
- event_type_canonical
- severity_canonical: info | low | medium | high | critical
- metric_value, metric_unit_canonical
- raw_payload_ref                      (traceability)
- ingest_batch_id, created_at
```

## Execution Plan — Phase by Phase

### Phase 0 — Repo & environment skeleton — ✅ Done
- Branch `feature/monitoring-backend` created and pushed.
- `docker-compose.yml`: `api`, `worker`, `postgres`, `redis`, `seed` services.
- App skeleton: `app/api`, `app/ingestion`, `app/normalization`, `app/processing`, `app/derivation`, `app/models`, `app/db`, `tests`.
- `scripts/seed_reference_data.py` loads `asset_reference.csv` / `line_reference.csv` into the DB on startup.
- Verified: `docker compose up --build` brings up all services; `GET /health` → `{"status":"ok"}`; `pytest` passes in-container.
- Note: dropped bind mounts (`.:/app`) — hit a Docker Desktop/WSL2 path bug on this Windows drive layout (`mkdir /run/desktop/mnt/host/d: file exists`). Image is rebuilt on `--build` instead of live-reloading from host.
- Commits: `chore: initialize project skeleton with Docker Compose, FastAPI, reference models, and seed script`, `docs: add project README, candidate brief`

### Phase 1 — Data models & migrations — ✅ Done
- SQLAlchemy models added: `RawBatch`/`RawEvent` (`app/models/raw.py`), `NormalizedEvent` (`app/models/normalized.py`), `MachineState` (`app/models/machine_state.py`), `DeadLetterEvent` (`app/models/dead_letter.py`), plus shared enums (`app/models/enums.py`) for status/category/severity, stored as validated strings rather than Postgres enum types.
- Unique constraint `(vendor, native_event_id)` on `raw_events` for dedupe.
- Alembic wired up (`alembic.ini`, `migrations/env.py`) with a hand-written initial migration (`migrations/versions/0001_initial_schema.py`) creating all 7 domain tables, indexes, and FKs.
- `docker-compose.yml` gained a `migrate` service (`alembic upgrade head`) that runs before `seed`; the seed script's ad-hoc `create_all` was removed since Alembic now owns the schema.
- Verified on a clean volume: `migrate` creates all 8 tables (7 domain + `alembic_version`) with correct constraints; `seed` loads reference data and is idempotent on re-run (8 asset rows, 5 line rows, unchanged on second run); `pytest` still passes.
- Not yet committed (held per instruction pending manual review).

### Phase 2 — Ingestion layer — ✅ Done
- `POST /v1/ingest/pulseforge`, `/v1/ingest/thermexwatch`, `/v1/ingest/maintaflow` (`app/api/ingest.py`), returning `202` with `batch_id` and per-batch accepted/duplicate/rejected counts.
- Per-vendor `X-Vendor-Key` header check (`app/ingestion/auth.py`).
- Envelope validation via loose per-vendor pydantic schemas (`app/ingestion/schemas.py`) — required top-level shape only; individual record contents stay untyped so malformed record fields don't reject the whole batch.
- `app/ingestion/service.py`: stores the raw batch verbatim (`raw_batches`) + one `raw_events` row per record (`status=pending`); dedupes on `(vendor, native_event_id)` against both existing DB rows and duplicates within the same batch (session autoflush is off, so an in-batch repeat needed an explicit `seen_in_batch` check, not just a DB query); records with no usable native id are stored as `status=failed` rather than dropped.
- Tests (`tests/test_ingestion.py`, 8 cases) against the real fixtures: happy path per vendor, wrong vendor key → 401, malformed envelope → 422, cross-batch dedupe (`pulseforge_sample.json` and `duplicates.json` intentionally share event id `PF-1001`), missing native id → rejected-not-dropped.
- Verified: fresh `docker compose up`, all 8 tests pass; manual curl checks (missing auth header → 422, live ingest → 202); direct DB check confirming `raw_events` counts match expectations per vendor/status.
- Process note: bind mounts were dropped in Phase 0, so host file edits don't reach a running container — `docker compose build` is required before re-running tests after a code change.
- Not yet committed (held per instruction pending manual review).

### Phase 3 — Normalization layer — ✅ Done
- Per-vendor mappers (`app/normalization/pulseforge.py`, `thermexwatch.py`, `maintaflow.py`): field mapping, timestamp parsing (`timestamps.py`: ISO8601 / epoch-ms / `YYYY/MM/DD HH:MM:SS`), °F→°C conversion, enum mapping (PulseForge event types and ThermexWatch alert codes both canonicalize to the same vocabulary, e.g. `VIB_WARN`→`HIGH_VIBRATION`; ThermexWatch level 1–5 → severity `info..critical`).
- **Assumption/trade-off called out**: ThermexWatch's `vibration_g` (acceleration) and PulseForge's `vibration_mm_s` (velocity) are different physical quantities and are *not* converted into each other — converting requires knowing vibration frequency, which isn't in the data. Stored as distinct units (`g` vs `mm_s`); cross-vendor vibration comparison is deferred to Phase 5's derivation rules.
- Machine resolution (`app/normalization/machine_resolution.py`) treats `asset_reference` as the source of truth for `plant_id`/`line_id` — vendor-supplied plant/line fields (e.g. ThermexWatch's bare-letter `productionLine`) are not trusted. Missing/blank id → `MISSING_MACHINE_ID`; id not found in reference data → `UNKNOWN_ASSET`.
- Invalid/unmappable fields (bad timestamp, unknown event/alert/record type, severity string, ThermexWatch level) → `INVALID_FIELD:<field>`, record fails; minor numeric issues (out-of-range confidence, non-numeric sensor reading) are non-fatal — value is nulled and flagged in `extra.data_quality_flags` instead of failing the whole record.
- MaintaFlow has no vendor-supplied severity field, so severity is derived by an explicit, documented heuristic (`major_defect_found`→critical, `overdue`→high, `minor_defect_found`→medium, else info) — a judgment call, not a vendor mapping.
- `app/normalization/service.py`: `normalize_raw_event()` dispatches by vendor, writes `NormalizedEvent` on success or `DeadLetterEvent` + `raw_event.status=failed` on `NormalizationError`; `normalize_pending_events()` batches this over all pending raw_events (synchronous for now — Phase 4 wraps it in the RQ worker). `scripts/normalize_pending.py` is a temporary manual trigger.
- Tests: `tests/test_normalization.py` (12 pure unit tests against `happy_path.json`/`malformed.json`/`conflicting_updates.json`/`retry_cases.json`, one per vendor happy path + each documented failure reason) + `tests/test_normalization_service.py` (1 integration test: ingest → normalize → DB, using `out_of_order.json`).
- Verified: 21/21 tests pass on a fresh volume; manual ingest of `malformed.json` + live `normalize_pending` run reproduced the exact expected classification (`MISSING_MACHINE_ID`, `INVALID_FIELD:event_time`, `INVALID_FIELD:alertCode` for the bad records; correct °F→°C conversion, e.g. 201°F → 93.89°C for a `TEMP_CRIT` reading) checked directly against `raw_events`/`dead_letter_events`/`normalized_events`.
- Not yet committed (held per instruction pending manual review).

### Phase 4 — Async processing & error handling — ✅ Done
- Redis + RQ wiring (`app/processing/queue.py`). Each ingestion endpoint now enqueues `normalize_batch(batch_id)` right after commit (`app/api/ingest.py`), instead of leaving records pending forever.
- `app/processing/jobs.py`: `normalize_batch()` normalizes only that batch's still-pending `raw_events` (scoped by `batch_id`, verified with a test proving a second in-flight batch is untouched), then enqueues `recompute_machine_state(machine_id)` for every machine that got a successfully normalized event.
- **Two-layer, documented retry design** (a single RQ-level retry on the whole batch wasn't enough — see reasoning): 
  1. Per-record (`app/normalization/service.py`): a `NormalizationError` (bad data) dead-letters immediately, since retrying won't fix invalid data. Any *other* exception increments `raw_event.retry_count` and leaves the record `pending` for a later run, up to `MAX_RECORD_RETRIES=3`, after which it's dead-lettered with `PROCESSING_ERROR:<ExceptionType>` — this stops a deterministic bug from retrying forever while still tolerating transient blips.
  2. Job-level (`BATCH_RETRY = Retry(max=3, interval=[10,30,60])` on `normalize_batch`): catches catastrophic failures outside the per-record loop (e.g. DB briefly unreachable). Safe to retry the whole job since it only re-selects rows still `pending`.
- `recompute_machine_state(machine_id)` is a documented placeholder for Phase 4 — it upserts a `machine_state` row (creating it from `asset_reference` if needed) and stamps `last_processed_at`/`processing_status`, proving the async chain end-to-end; Phase 5 replaces the body with the real rule engine.
- Tests (`tests/test_processing.py`, 3 cases): unexpected-error retry-then-dead-letter (monkeypatched normalizer raising `RuntimeError`, asserts `retry_count` increments 1→2→3 and dead-letters on the 3rd attempt with the right reason), `normalize_batch` only touches its own batch, `recompute_machine_state` creates/updates the row correctly.
- Verified live end-to-end (not just unit tests): ingested `pulseforge_sample.json` over HTTP against the real `docker compose` stack, watched the `worker` container's logs process `normalize_batch` → chain-enqueue `recompute_machine_state('EQ-001')` and `('EQ-002')` → both complete, then confirmed in Postgres that `raw_events.status='normalized'` for both records and `machine_state` rows exist with correct `plant_id`/`line_id`/`last_processed_at`.
- Not yet committed (held per instruction pending manual review).

### Phase 5 — Derivation rule engine — ✅ Done
- Pure rule engine (`app/derivation/rules.py::evaluate_machine`): severity ladder `info..critical` → `attention_level` 1–5 → `derived_status` OK/WATCH/ATTENTION/CRITICAL. Rules: vendor-reported critical/high severity, temperature/vibration above the machine's own rated thresholds (`asset_reference.rated_max_temp_c`/`rated_max_vibration_mm_s`, mm_s only — see Phase 3's g-vs-mm_s note, verified with a dedicated test that a large g-unit reading does *not* trip `VIB_ABOVE_RATED`), low sensor confidence, `maintenance_status=overdue`, `inspection_result` minor/major defect. A high-`criticality` asset sitting at ATTENTION is escalated one notch to CRITICAL (`HIGH_CRITICALITY_ESCALATION`) — the same reading matters more on equipment that can least afford to fail.
- **Conflict resolution by `event_time_utc`, not receipt order**: `app/derivation/service.py::get_latest_by_category` queries each machine's `normalized_events` sorted ascending by `event_time_utc` and keeps the last row per category — so whichever event is chronologically latest always wins the "current reading" slot, regardless of insert/receipt order. Verified with a dedicated test: a calm reading (later `event_time_utc`) ingested *before* a high-severity warning (earlier `event_time_utc`, received second) — the calm reading still wins, proving receipt order has no effect. Also verified against the real `conflicting_updates.json` fixture across all three vendors landing on the same machine (EQ-008).
- **Staleness uses the dataset's own clock, not wall-clock time** (`get_dataset_now`: `max(event_time_utc)` across all normalized events) — documented assumption, since the sample data is a fixed historical batch and comparing against real "now" would mark every machine stale regardless of actual data freshness. `processing_status`: `ok` (fresh), `stale` (>2h behind the dataset clock), `failed` (no normalized signal at all for the machine). **Known limitation, explicitly deferred**: a `partial` status (some vendor data rejected for this machine) was scoped out — `dead_letter_events` doesn't carry a resolved `machine_id` (only the vendor-specific raw payload), so linking a dead-lettered record back to a machine would need per-vendor extraction logic; not worth the complexity for this assessment.
- `app/processing/jobs.py::recompute_machine_state` now calls `app.derivation.service.compute_and_store`, replacing Phase 4's placeholder body — the async wiring itself didn't need to change.
- Tests: `tests/test_derivation.py` (10 pure unit tests, synthetic events, one per rule + staleness) + `tests/test_derivation_service.py` (2 integration tests: the `conflicting_updates.json` multi-vendor-agreement case, and the synthetic out-of-order same-category case above).
- Verified: 36/36 tests pass on a fresh volume; live run against the real stack — ingested `conflicting_updates.json` over HTTP across all 3 vendor endpoints, confirmed `machine_state` for EQ-008 shows `derived_status=CRITICAL`, `attention_level=5`, `reason_codes=["VENDOR_CRITICAL_ALERT","TEMP_ABOVE_RATED","MAJOR_DEFECT_FOUND"]`, `processing_status=ok`.
- Not yet committed (held per instruction pending manual review).

### Phase 6 — Output APIs — ✅ Done
- `GET /v1/ingest/status/{batch_id}` (`app/api/status.py`) — pending/normalized/failed counts plus a `dead_letters` list (native id + reason) joined from `dead_letter_events`. `404` for unknown batch, `422` for a non-UUID batch id.
- `GET /v1/machines/{machine_id}` and `GET /v1/machines?plant_id=&line_id=&status=` (`app/api/machines.py`) — the attention view, matching `expected_output_context.md`'s minimum fields (`derived_status`, `attention_level`, `reason_codes`, `latest_relevant_event_time`, `processing_status`, `source_event_refs`, `last_processed_at`) plus `criticality` (bonus field — explains *why* `HIGH_CRITICALITY_ESCALATION` fired). `404` for a `machine_id` not in `asset_reference`.
- **Machines with no data yet still appear**, with explicit defaults (`derived_status=OK`, `processing_status=failed` meaning "nothing processed", empty `reason_codes`) — the list is built from `asset_reference` left-joined with `machine_state` (`app/api/machine_views.py`), not from `machine_state` alone, so a plant/line view never silently drops machines that haven't reported anything.
- `GET /v1/plants/{plant_id}/summary` and `GET /v1/lines/{line_id}/summary` (`app/api/summary.py`) — status counts, list of currently-critical machines, stale/failed counts, and per-line breakdowns sorted by attention count descending (most machines needing attention first). `404` for an unknown plant/line.
- Tests: `tests/test_output_apis.py` (10 integration tests) — batch status with real dead-letter reasons, unknown/malformed batch id, machine view reflecting real derivation output (`conflicting_updates.json` → EQ-008 CRITICAL), unknown machine 404, untouched-machine defaults (EQ-005, never touched by any test), filtered machine list, plant/line summary reflecting the critical machine and its line, unknown plant/line 404.
- Verified: 46/46 tests pass on a fresh volume; live run against the real stack — ingested `pulseforge_sample.json` over HTTP, then hit all 5 new endpoints and confirmed the numbers by hand (EQ-001: `HIGH_VIBRATION`/high severity + `vibration_mm_s=11.8` > rated `9.0` → `VIB_ABOVE_RATED` + `VENDOR_HIGH_ALERT` → ATTENTION, escalated to CRITICAL since `criticality=high`; EQ-002: `TEMP_SPIKE`/critical + `96.4°C` > rated `90.0°C` → CRITICAL directly); confirmed all 8 routes appear in `/openapi.json`.
- Not yet committed (held per instruction pending manual review).

### Phase 7 — Documentation & polish — ✅ Done
- **README.md** rewritten from the Phase-0-era draft: architecture overview (with an ASCII diagram — see below), full project layout, `docker compose` setup/run/test instructions, an API overview table for all 8 endpoints with a worked `curl` example, assumptions & trade-offs (reference-data-as-ground-truth, no vibration-unit conversion, dataset-clock staleness, `partial` status scoped out, per-vendor API keys), limitations/production-next-steps (pagination, read-API auth, read replicas, observability, rate limiting, autogenerated migrations going forward), the known Docker bind-mount issue, and an AI usage disclosure section.
- **Architecture diagram**: kept as a simple ASCII diagram inline in the README rather than a separate image file — matches the brief's "simple, not over-engineered" guidance and needs no extra tooling to view/keep in sync with the text around it.
- **API contract**: FastAPI's auto-generated OpenAPI schema (`/openapi.json`, Swagger UI at `/docs`) is the contract, referenced from the README rather than duplicated into a static file that would drift from the code.
- **`DESIGN_NOTE.md`** (new, separate from the README as the brief asks): the "why" behind five decisions — canonical event model, reference-data-as-ground-truth, event-time-based conflict resolution, the two-layer retry design, the flat rule-table approach — plus an explicit "what was deliberately left out, and why" section.
- Verified: re-ran the full test suite after this phase (`46 passed`, unchanged — this phase touched only docs) on a fresh volume, confirming nothing was accidentally broken while writing the docs.
- Not yet committed (held per instruction pending manual review).

### Post-Phase-7 fixes — two bugs found on review — ✅ Done
A manual review (prompted by "is there any other issue besides the known Docker one?") surfaced two real gaps in already-"done" phases — not trade-offs, actual bugs:
1. **Per-record retry was dead code in the deployed pipeline** (Phase 4 gap): `normalize_raw_event` leaves a record `pending` and increments `retry_count` on an unexpected error, but never raises — so the RQ job reports success and nothing ever automatically re-attempts that record. Fixed: `normalize_batch` (`app/processing/jobs.py`) now checks the `pending` count after each run and re-enqueues itself (`enqueue_in`, 15s delay) when anything is still pending — bounded, since each attempt moves a record toward `MAX_RECORD_RETRIES` and then it's dead-lettered.
2. **Dedupe race condition** (Phase 2 gap): `ingest_batch` used check-then-insert against `(vendor, native_event_id)`, so two concurrent requests for the same native id could both pass the check and then collide on commit, failing the whole batch. Fixed: replaced with an atomic Postgres `INSERT ... ON CONFLICT DO NOTHING ... RETURNING` (`app/ingestion/service.py`) — the database resolves the race, not a Python-side check.
- Full reasoning for both recorded in `DESIGN_NOTE.md` under "Two bugs found on review, and how they were fixed."
- New tests: `tests/test_processing.py` (+2: normalize_batch re-enqueues when pending>0 / does not when pending=0, via monkeypatched queue) and `tests/test_ingestion.py` (+1: dedupe holds against a row inserted directly to simulate a concurrent request, proving the atomic conflict handling — not a Python-side pre-check — is what catches it).
- Verified: 49/49 tests pass on a fresh volume; live re-run of the Phase 4 end-to-end check (ingest over HTTP → worker logs → DB state) still passes with the fix in place.
- Not yet committed (held per instruction pending manual review).

### Phase 8 — Final review pass — ✅ Done (commit/PR intentionally skipped, per instruction)
- **Fixture coverage check**: confirmed every file in `vendor_api_samples/` (`pulseforge_sample`, `thermexwatch_sample`, `maintaflow_sample`, `happy_path`, `duplicates`, `malformed`, `out_of_order`, `conflicting_updates`, `retry_cases`) is referenced by at least one test — grepped `tests/` for each filename.
- **Clean-checkout sanity check**: `docker compose down -v` + `docker image prune -f` + `docker compose build --no-cache` (forces a from-scratch rebuild, no layer cache) → `docker compose up -d` → all services healthy, `GET /health` → `{"status":"ok"}`.
- **Full test suite on the clean build**: `docker compose run --rm api pytest -v` → **49/49 passed**, all fixture-backed tests included.
- **Commit history review**: 10 commits on `feature/monitoring-backend` (all by the repo owner, not by me — I was instructed not to commit), one phase-sized commit each, messages match what was actually built per phase. One local commit (`746e59b`, the two bug fixes) is ahead of `origin/feature/monitoring-backend` and not yet pushed. Working tree currently has `README.md` modified and `DESIGN_NOTE.md`/`IMPLEMENTATION_PLAN.md`/the candidate brief untracked — all Phase 7 documentation, intentionally left uncommitted per instruction.
- **Commit and PR were explicitly skipped this phase** — the user asked to proceed with Phase 8's review activities only, without committing or opening a PR. Once the user is ready: commit the doc changes, push, then open a PR from `feature/monitoring-backend` into `main`.
