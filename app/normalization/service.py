import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.dead_letter import DeadLetterEvent
from app.models.enums import RawEventStatus
from app.models.normalized import NormalizedEvent
from app.models.raw import RawEvent
from app.models.reference import AssetReference
from app.normalization import maintaflow, pulseforge, thermexwatch
from app.normalization.errors import NormalizationError

_NORMALIZERS = {
    "pulseforge": pulseforge.normalize,
    "thermexwatch": thermexwatch.normalize,
    "maintaflow": maintaflow.normalize,
}

# Caps retries for *unexpected* errors during normalization (e.g. a transient
# DB hiccup, or a bug tripping on a record shape we didn't anticipate). Bad
# data that we understand (NormalizationError) is never retried — it goes
# straight to dead-letter since retrying won't change the outcome.
MAX_RECORD_RETRIES = 3


@dataclass
class NormalizeOutcome:
    status: str
    machine_id: Optional[str] = None


def load_asset_lookup(db: Session) -> Dict[str, AssetReference]:
    return {asset.machine_id: asset for asset in db.execute(select(AssetReference)).scalars().all()}


def _dead_letter(db: Session, raw_event: RawEvent, reason: str, now: datetime) -> None:
    raw_event.status = RawEventStatus.FAILED.value
    raw_event.error_reason = reason
    raw_event.processed_at = now
    db.add(
        DeadLetterEvent(
            id=uuid.uuid4(),
            raw_event_id=raw_event.id,
            vendor=raw_event.vendor,
            reason=reason,
            raw_record=raw_event.raw_record,
            retry_count=raw_event.retry_count,
        )
    )


def normalize_raw_event(
    db: Session, raw_event: RawEvent, asset_lookup: Dict[str, AssetReference]
) -> NormalizeOutcome:
    """Normalizes one raw_event in place, persisting the outcome.

    - A `NormalizationError` (bad/unresolvable data) dead-letters immediately —
      retrying wouldn't help, the data itself is invalid.
    - Any other exception is treated as possibly transient: retry_count is
      incremented and the record is left `pending` (a later run will pick it
      up again) until MAX_RECORD_RETRIES is exceeded, at which point it's
      dead-lettered too so it doesn't get stuck retrying forever.
    """
    normalizer = _NORMALIZERS[raw_event.vendor]
    now = datetime.now(timezone.utc)

    try:
        data = normalizer(raw_event.raw_record, asset_lookup)
    except NormalizationError as exc:
        _dead_letter(db, raw_event, exc.reason, now)
        db.commit()
        return NormalizeOutcome(status=RawEventStatus.FAILED.value)
    except Exception as exc:
        raw_event.retry_count += 1
        if raw_event.retry_count >= MAX_RECORD_RETRIES:
            _dead_letter(db, raw_event, f"PROCESSING_ERROR:{type(exc).__name__}", now)
        else:
            raw_event.status = RawEventStatus.PENDING.value
        db.commit()
        return NormalizeOutcome(status=raw_event.status)

    db.add(
        NormalizedEvent(
            id=uuid.uuid4(),
            raw_event_id=raw_event.id,
            vendor=raw_event.vendor,
            machine_id=data.machine_id,
            plant_id=data.plant_id,
            line_id=data.line_id,
            event_time_utc=data.event_time_utc,
            category=data.category,
            event_type_canonical=data.event_type_canonical,
            severity_canonical=data.severity_canonical,
            metric_value=data.metric_value,
            metric_unit_canonical=data.metric_unit_canonical,
            extra=data.extra,
        )
    )
    raw_event.status = RawEventStatus.NORMALIZED.value
    raw_event.error_reason = None
    raw_event.processed_at = now
    db.commit()
    return NormalizeOutcome(status=RawEventStatus.NORMALIZED.value, machine_id=data.machine_id)


def normalize_events(db: Session, raw_events) -> Dict[str, object]:
    """Normalizes a given list of raw_events. Returns counts plus the set of
    machine ids that received at least one successfully normalized event
    (used to know which machines need `recompute_machine_state`)."""
    asset_lookup = load_asset_lookup(db)
    counts = {"normalized": 0, "failed": 0, "pending": 0}
    affected_machines = set()

    for raw_event in raw_events:
        outcome = normalize_raw_event(db, raw_event, asset_lookup)
        counts[outcome.status] += 1
        if outcome.machine_id:
            affected_machines.add(outcome.machine_id)

    return {"counts": counts, "affected_machines": affected_machines}


def normalize_pending_events(db: Session) -> Dict[str, int]:
    """Normalizes every pending raw_event regardless of batch. Kept for manual/
    ad-hoc use (see scripts/normalize_pending.py); the worker path normalizes
    one batch at a time via app.processing.jobs.normalize_batch."""
    pending = db.execute(
        select(RawEvent).where(RawEvent.status == RawEventStatus.PENDING.value)
    ).scalars().all()
    result = normalize_events(db, pending)
    return result["counts"]
