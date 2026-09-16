from datetime import datetime, timezone

from rq import Retry
from sqlalchemy import select

from app.db.session import SessionLocal
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
    """Materializes the derived attention view for one machine.

    Placeholder body for Phase 4 — it proves the async hook (normalize ->
    enqueue -> recompute) works end-to-end. Phase 5 replaces the body with
    the real rule engine; the row this creates/touches is what Phase 5's
    rules will overwrite with derived_status/attention_level/reason_codes.
    """
    from app.models.machine_state import MachineState
    from app.models.reference import AssetReference

    db = SessionLocal()
    try:
        state = db.get(MachineState, machine_id)
        now = datetime.now(timezone.utc)

        if state is None:
            asset = db.get(AssetReference, machine_id)
            if asset is None:
                return
            state = MachineState(
                machine_id=machine_id,
                plant_id=asset.plant_id,
                line_id=asset.line_id,
                derived_status="OK",
                attention_level=1,
                reason_codes=[],
                processing_status="ok",
                source_event_refs=[],
            )
            db.add(state)

        state.last_processed_at = now
        state.processing_status = "ok"
        db.commit()
    finally:
        db.close()
