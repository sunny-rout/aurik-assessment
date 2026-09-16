import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import BatchStatusResponse, DeadLetterInfo
from app.db.session import get_db
from app.models.dead_letter import DeadLetterEvent
from app.models.enums import RawEventStatus
from app.models.raw import RawBatch, RawEvent

router = APIRouter(prefix="/v1/ingest", tags=["ingestion-status"])


@router.get("/status/{batch_id}", response_model=BatchStatusResponse)
def get_batch_status(batch_id: str, db: Session = Depends(get_db)):
    try:
        batch_uuid = uuid.UUID(batch_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="batch_id must be a UUID")

    batch = db.get(RawBatch, batch_uuid)
    if batch is None:
        raise HTTPException(status_code=404, detail="unknown batch_id")

    events = db.execute(select(RawEvent).where(RawEvent.batch_id == batch_uuid)).scalars().all()
    counts = {status.value: 0 for status in RawEventStatus}
    for event in events:
        counts[event.status] = counts.get(event.status, 0) + 1

    dead_letters = db.execute(
        select(DeadLetterEvent, RawEvent.native_event_id)
        .join(RawEvent, DeadLetterEvent.raw_event_id == RawEvent.id)
        .where(RawEvent.batch_id == batch_uuid)
    ).all()

    return BatchStatusResponse(
        batch_id=str(batch.id),
        vendor=batch.vendor,
        received_at=batch.received_at,
        total_records=len(events),
        pending=counts[RawEventStatus.PENDING.value],
        normalized=counts[RawEventStatus.NORMALIZED.value],
        failed=counts[RawEventStatus.FAILED.value],
        dead_letters=[
            DeadLetterInfo(
                raw_event_id=str(dl.raw_event_id),
                native_event_id=native_id,
                reason=dl.reason,
            )
            for dl, native_id in dead_letters
        ],
    )
