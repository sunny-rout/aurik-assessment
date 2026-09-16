from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.ingestion.auth import require_vendor_key
from app.ingestion.schemas import (
    IngestResponse,
    MaintaFlowEnvelope,
    PulseForgeEnvelope,
    ThermexWatchEnvelope,
)
from app.ingestion.service import ingest_batch

router = APIRouter(prefix="/v1/ingest", tags=["ingestion"])


def _to_response(vendor: str, result) -> IngestResponse:
    return IngestResponse(
        batch_id=str(result.batch_id),
        vendor=vendor,
        total_records=result.total_records,
        accepted=result.accepted,
        duplicates=result.duplicates,
        rejected=result.rejected,
    )


@router.post("/pulseforge", status_code=202, response_model=IngestResponse)
def ingest_pulseforge(
    payload: PulseForgeEnvelope,
    db: Session = Depends(get_db),
    _auth: None = Depends(require_vendor_key("pulseforge")),
):
    result = ingest_batch(
        db,
        vendor="pulseforge",
        envelope_payload=payload.model_dump(),
        records=payload.events,
        native_id_field="event_id",
    )
    return _to_response("pulseforge", result)


@router.post("/thermexwatch", status_code=202, response_model=IngestResponse)
def ingest_thermexwatch(
    payload: ThermexWatchEnvelope,
    db: Session = Depends(get_db),
    _auth: None = Depends(require_vendor_key("thermexwatch")),
):
    result = ingest_batch(
        db,
        vendor="thermexwatch",
        envelope_payload=payload.model_dump(),
        records=payload.readings,
        native_id_field="readingId",
    )
    return _to_response("thermexwatch", result)


@router.post("/maintaflow", status_code=202, response_model=IngestResponse)
def ingest_maintaflow(
    payload: MaintaFlowEnvelope,
    db: Session = Depends(get_db),
    _auth: None = Depends(require_vendor_key("maintaflow")),
):
    result = ingest_batch(
        db,
        vendor="maintaflow",
        envelope_payload=payload.model_dump(),
        records=payload.records,
        native_id_field="record_id",
    )
    return _to_response("maintaflow", result)
