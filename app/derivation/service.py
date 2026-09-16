from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.derivation.result import DerivationResult
from app.derivation.rules import evaluate_machine
from app.models.machine_state import MachineState
from app.models.normalized import NormalizedEvent
from app.models.reference import AssetReference


def get_latest_by_category(db: Session, machine_id: str) -> Dict[str, NormalizedEvent]:
    """Returns the latest NormalizedEvent per category for a machine, where
    "latest" means highest event_time_utc — not receipt/insert order. This is
    what makes derivation resilient to out-of-order or conflicting updates:
    sorting ascending and letting later writes overwrite earlier ones in the
    dict means the chronologically-last event always wins, however it arrived.
    """
    events = db.execute(
        select(NormalizedEvent)
        .where(NormalizedEvent.machine_id == machine_id)
        .order_by(NormalizedEvent.event_time_utc.asc())
    ).scalars().all()

    latest: Dict[str, NormalizedEvent] = {}
    for event in events:
        latest[event.category] = event
    return latest


def get_dataset_now(db: Session) -> datetime:
    """The dataset's own clock: the latest event_time_utc seen anywhere.

    Used instead of real wall-clock time so staleness reflects the data's
    own internal freshness rather than how long ago this fixed sample batch
    happens to be relative to whenever the system is actually running.
    """
    latest = db.execute(select(func.max(NormalizedEvent.event_time_utc))).scalar()
    return latest or datetime.now(timezone.utc)


def compute_and_store(db: Session, machine_id: str) -> Optional[DerivationResult]:
    asset = db.get(AssetReference, machine_id)
    if asset is None:
        return None

    latest_by_category = get_latest_by_category(db, machine_id)
    dataset_now = get_dataset_now(db)
    result = evaluate_machine(asset, latest_by_category, dataset_now)

    state = db.get(MachineState, machine_id)
    if state is None:
        state = MachineState(machine_id=machine_id)
        db.add(state)

    state.plant_id = asset.plant_id
    state.line_id = asset.line_id
    state.derived_status = result.derived_status
    state.attention_level = result.attention_level
    state.reason_codes = result.reason_codes
    state.latest_relevant_event_time = result.latest_relevant_event_time
    state.processing_status = result.processing_status
    state.source_event_refs = result.source_event_refs
    state.last_processed_at = datetime.now(timezone.utc)
    db.commit()

    return result
