from datetime import timedelta

from rq import Retry
from sqlalchemy import select

from app.db.session import SessionLocal
from app.derivation.service import compute_and_store
from app.models.enums import RawEventStatus
from app.models.raw import RawEvent
from app.normalization.service import normalize_events
from app.processing.queue import get_queue

# Whole-job retry for genuinely transient failures (e.g. DB briefly
# unreachable) that happen *outside* the per-record handling in
# normalize_events — that function already isolates per-record errors so a
# retry here just re-runs the batch, which is safe/idempotent since it only
# re-selects rows still marked pending.
BATCH_RETRY = Retry(max=3, interval=[10, 30, 60])

# Delay before re-checking a batch that still has records stuck `pending`
# after an unexpected (not NormalizationError) per-record failure. Without
# this, normalize_events() swallows the exception internally and the job
# reports success to RQ, so nothing would ever automatically re-attempt
# those records — retry_count would be incremented once and then the record
# would sit pending forever. Re-enqueuing here is what actually drives a
# record through its retry_count attempts up to MAX_RECORD_RETRIES.
RECORD_RETRY_DELAY = timedelta(seconds=15)


def normalize_batch(batch_id: str) -> dict:
    db = SessionLocal()
    try:
        pending = db.execute(
            select(RawEvent).where(
                RawEvent.batch_id == batch_id, RawEvent.status == RawEventStatus.PENDING.value
            )
        ).scalars().all()

        result = normalize_events(db, pending)

        for machine_id in result["affected_machines"]:
            get_queue().enqueue(recompute_machine_state, machine_id)

        if result["counts"]["pending"] > 0:
            # some records hit an unexpected error and are still pending —
            # re-run this batch shortly. normalize_events() only re-selects
            # rows still marked pending, so this is safe to repeat, and each
            # attempt moves affected records closer to MAX_RECORD_RETRIES,
            # so this self-reschedule is bounded, not an infinite loop.
            get_queue().enqueue_in(RECORD_RETRY_DELAY, normalize_batch, batch_id)

        return result
    finally:
        db.close()


def recompute_machine_state(machine_id: str) -> None:
    """Materializes the derived attention view for one machine, via the rule
    engine in app.derivation (see rules.py for the actual logic)."""
    db = SessionLocal()
    try:
        compute_and_store(db, machine_id)
    finally:
        db.close()
