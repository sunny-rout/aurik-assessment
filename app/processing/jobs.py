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
