import uuid
from dataclasses import dataclass
from typing import Any, Dict, List

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.enums import RawEventStatus
from app.models.raw import RawBatch, RawEvent


@dataclass
class IngestResult:
    batch_id: uuid.UUID
    total_records: int
    accepted: int
    duplicates: int
    rejected: int


def ingest_batch(
    db: Session,
    vendor: str,
    envelope_payload: Dict[str, Any],
    records: List[Dict[str, Any]],
    native_id_field: str,
) -> IngestResult:
    """Stores a vendor batch verbatim and one raw_event row per record.

    Records missing a usable native id are stored with status=failed rather
    than dropped, so nothing silently disappears. Records that already exist
    for this vendor (same native id) are counted as duplicates and skipped —
    re-posting the same batch is a no-op.

    Dedupe is enforced atomically via `ON CONFLICT DO NOTHING` against the
    `(vendor, native_event_id)` unique constraint, rather than a
    check-then-insert — two concurrent requests for the same native id (e.g.
    a vendor retrying a POST) can't both pass a pre-check and then collide
    on commit; the database resolves the race directly.
    """
    batch = RawBatch(vendor=vendor, raw_payload=envelope_payload)
    db.add(batch)
    db.flush()

    accepted = 0
    duplicates = 0
    rejected = 0
    seen_in_batch = set()
    candidate_rows = []

    for record in records:
        native_id = record.get(native_id_field)

        if not native_id:
            db.add(
                RawEvent(
                    batch_id=batch.id,
                    vendor=vendor,
                    native_event_id=f"_missing_id_{uuid.uuid4()}",
                    raw_record=record,
                    status=RawEventStatus.FAILED.value,
                    error_reason="MISSING_NATIVE_EVENT_ID",
                )
            )
            rejected += 1
            continue

        native_id = str(native_id)
        if native_id in seen_in_batch:
            duplicates += 1
            continue
        seen_in_batch.add(native_id)
        candidate_rows.append(
            {
                "batch_id": batch.id,
                "vendor": vendor,
                "native_event_id": native_id,
                "raw_record": record,
                "status": RawEventStatus.PENDING.value,
            }
        )

    if candidate_rows:
        stmt = (
            pg_insert(RawEvent)
            .values(candidate_rows)
            .on_conflict_do_nothing(constraint="uq_raw_events_vendor_native_id")
            .returning(RawEvent.native_event_id)
        )
        inserted_ids = set(db.execute(stmt).scalars().all())
        accepted = len(inserted_ids)
        duplicates += len(candidate_rows) - accepted

    db.commit()

    return IngestResult(
        batch_id=batch.id,
        total_records=len(records),
        accepted=accepted,
        duplicates=duplicates,
        rejected=rejected,
    )
