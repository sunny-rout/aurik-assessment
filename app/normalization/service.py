import uuid
from datetime import datetime, timezone
from typing import Dict

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


def load_asset_lookup(db: Session) -> Dict[str, AssetReference]:
    return {asset.machine_id: asset for asset in db.execute(select(AssetReference)).scalars().all()}


def normalize_raw_event(db: Session, raw_event: RawEvent, asset_lookup: Dict[str, AssetReference]) -> str:
    """Normalizes one raw_event in place, persisting the outcome.

    Returns the resulting raw_event status ("normalized" or "failed").
    """
    normalizer = _NORMALIZERS[raw_event.vendor]
    now = datetime.now(timezone.utc)

    try:
        data = normalizer(raw_event.raw_record, asset_lookup)
    except NormalizationError as exc:
        raw_event.status = RawEventStatus.FAILED.value
        raw_event.error_reason = exc.reason
        raw_event.processed_at = now
        db.add(
            DeadLetterEvent(
                id=uuid.uuid4(),
                raw_event_id=raw_event.id,
                vendor=raw_event.vendor,
                reason=exc.reason,
                raw_record=raw_event.raw_record,
            )
        )
        db.commit()
        return RawEventStatus.FAILED.value

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
    return RawEventStatus.NORMALIZED.value


def normalize_pending_events(db: Session) -> Dict[str, int]:
    """Normalizes every raw_event currently pending. Synchronous helper used
    directly for now; Phase 4 wraps this in an async worker job."""
    asset_lookup = load_asset_lookup(db)
    pending = db.execute(
        select(RawEvent).where(RawEvent.status == RawEventStatus.PENDING.value)
    ).scalars().all()

    counts = {"normalized": 0, "failed": 0}
    for raw_event in pending:
        result_status = normalize_raw_event(db, raw_event, asset_lookup)
        counts[result_status] += 1
    return counts
