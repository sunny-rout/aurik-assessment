import json

from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.service import ingest_batch
from app.models.enums import RawEventStatus
from app.models.normalized import NormalizedEvent
from app.models.raw import RawEvent
from app.normalization.service import normalize_pending_events

FIXTURES_DIR = "Aurik_Tech_Lead_Assessment_Assets/vendor_api_samples"


def _load(name: str) -> dict:
    with open(f"{FIXTURES_DIR}/{name}", encoding="utf-8") as f:
        return json.load(f)


def test_ingest_then_normalize_end_to_end():
    db = SessionLocal()
    try:
        payload = _load("out_of_order.json")["pulseforge"]
        ingest_batch(
            db,
            vendor="pulseforge",
            envelope_payload=payload,
            records=payload["events"],
            native_id_field="event_id",
        )

        counts = normalize_pending_events(db)
        assert counts["normalized"] >= 2

        normalized = db.execute(
            select(NormalizedEvent).where(NormalizedEvent.vendor == "pulseforge")
        ).scalars().all()
        assert any(n.event_type_canonical == "RECOVERY_SIGNAL" for n in normalized)

        remaining_pending = db.execute(
            select(RawEvent).where(
                RawEvent.vendor == "pulseforge", RawEvent.status == RawEventStatus.PENDING.value
            )
        ).scalars().all()
        assert remaining_pending == []
    finally:
        db.close()
