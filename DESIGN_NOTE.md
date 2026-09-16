# Design Note

Short version: three vendors, three schemas, one canonical event shape, an async
pipeline that turns raw vendor noise into a deterministic per-machine "does this
need attention" answer. This note covers the decisions that shaped that pipeline
and why, not a repeat of the README's setup/API instructions.

## Why a canonical event model, not per-vendor storage

Every vendor's raw payload is kept verbatim (`raw_batches`/`raw_events`) for
traceability, but everything downstream — derivation, output APIs — only ever
looks at one shape: `NormalizedEvent` (`category`, `event_type_canonical`,
`severity_canonical`, `metric_value`/`metric_unit_canonical`, plus a per-vendor
`extra` bag for fields that don't generalize). This is what lets the derivation
rule engine be vendor-agnostic: it doesn't know or care whether a "high vibration"
signal came from PulseForge or ThermexWatch, because both normalizers map their
vendor-specific alert codes into the same canonical vocabulary
(`HIGH_VIBRATION`, `TEMP_SPIKE`, ...). Adding a 4th vendor means writing one new
normalizer, not touching ingestion, derivation, or the APIs.

## Why reference data is the source of truth for plant/line

Vendor-supplied plant/line fields are inconsistent (ThermexWatch's
`productionLine` is a bare letter, not `LINE-X`) and not always trustworthy —
this is exactly the kind of "vendor data isn't clean" problem the brief calls
out. Rather than reconcile three different plant/line conventions, machine
resolution (`app/normalization/machine_resolution.py`) looks up the *machine id*
in `asset_reference.csv` and takes plant/line from there. A vendor's own
plant/line claims are discarded. This also means a machine can only ever belong
to one plant/line, by construction, no matter what a vendor's payload says.

## Why conflict resolution is by event_time, not receipt order

`out_of_order.json` and `conflicting_updates.json` exist specifically to test
this: vendor data doesn't arrive in chronological order, and different vendors
can disagree about a machine's current state at overlapping times. The fix
(`app/derivation/service.py::get_latest_by_category`) is to always ask "what is
the highest `event_time_utc` reading for this category" at query time, rather
than tracking "the last thing we received." This makes the system naturally
correct under retries, network reordering, and multi-vendor overlap without any
explicit reordering logic — it falls out of always querying by timestamp.

## Why two layers of retry, not one

A single job-level retry (retry the whole batch) can't tell the difference
between "the database was briefly unreachable" (worth retrying) and "this
specific record has a machine_id we've never seen" (retrying won't help — it's
not going to appear in `asset_reference` on attempt 2). Conflating those means
either retrying forever on bad data, or dead-lettering good data after one
infrastructure blip. So there are two layers:
- **Per-record** (`app/normalization/service.py`): a `NormalizationError` — data
  we understand and know is invalid — dead-letters immediately. Anything else
  (a genuinely unexpected exception) gets a bounded number of retries via
  `retry_count` before giving up.
- **Per-batch** (`app/processing/jobs.py`, RQ's own `Retry`): catches failures
  outside the per-record loop entirely (e.g. losing the DB connection mid-batch).
  Safe to retry the whole job because it only re-selects rows still `pending`.

## Why the rule engine is a flat rule table, not a scoring model

The brief explicitly prefers deterministic, explainable logic over ML. A flat
table of (condition → reason code → attention level) means every derived status
comes with a human-readable list of *why* — `reason_codes` — which is what the
brief's "explainable" output requirement actually asks for. The one piece of
nuance is the criticality escalation (a `high`-criticality asset at ATTENTION
becomes CRITICAL): even that is a single, named, always-visible rule
(`HIGH_CRITICALITY_ESCALATION`), not a hidden weighting.

## Two bugs found on review, and how they were fixed

A later review surfaced two real gaps, not deliberate trade-offs — worth
recording since they explain code that might otherwise look redundant:

- **The per-record retry path was effectively dead in the deployed pipeline.**
  `normalize_raw_event` catches unexpected exceptions, bumps `retry_count`, and
  leaves the record `pending` for "a later run." But it swallows the exception
  rather than raising, so the RQ job reports success and nothing automatically
  re-attempts that record — it would sit `pending` forever. Fixed by having
  `normalize_batch` check the `pending` count after each attempt and
  re-enqueue itself with a short delay (`app/processing/jobs.py`) when
  anything is still pending. This is safe to repeat (each run only re-selects
  rows still `pending`) and self-terminating (each attempt moves a record
  closer to `MAX_RECORD_RETRIES`, after which it's dead-lettered and the
  `pending` count drops to zero).
- **A dedupe race in ingestion.** `ingest_batch` checked "does this native id
  already exist?" and only then inserted — two concurrent requests for the
  same native id could both pass that check before either committed, and the
  second would fail the whole batch's commit with an `IntegrityError` on the
  unique constraint. Fixed by replacing check-then-insert with a single
  atomic `INSERT ... ON CONFLICT DO NOTHING ... RETURNING` (Postgres-specific,
  `app/ingestion/service.py`), so the database — not a Python-side race —
  resolves the conflict.

## What was deliberately left out, and why

- **Cross-unit vibration comparison** (PulseForge's `mm_s` vs ThermexWatch's
  `g`): these are different physical quantities (velocity vs. acceleration);
  converting between them needs the vibration frequency, which isn't in the
  data. Rather than fabricate a conversion, they're kept as separate units, and
  only PulseForge's mm_s readings get the rated-threshold check.
- **`partial` processing status**: `dead_letter_events` doesn't carry a resolved
  `machine_id` (only the vendor's raw payload, since the failure often *is* that
  the machine id couldn't be resolved). Building this would mean vendor-specific
  best-effort id extraction on the dead-letter path — a second, weaker copy of
  the normalization logic, just for a status label. Not worth it here.
- **Wall-clock staleness**: the sample data is a fixed historical batch, so
  "how long ago, right now" would mark everything stale on every run.
  Staleness instead compares against the dataset's own latest timestamp — a
  reasonable stand-in for "latest known signal time," which is what a real
  monitoring system would often use anyway when reasoning about batch/replay
  data.
