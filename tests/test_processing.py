import json

from sqlalchemy import select

from app.db.session import SessionLocal
from app.ingestion.service import ingest_batch
from app.models.machine_state import MachineState
from app.models.raw import RawEvent
from app.normalization import service as normalization_service
from app.processing import jobs as processing_jobs

FIXTURES_DIR = "Aurik_Tech_Lead_Assessment_Assets/vendor_api_samples"


def _load(name: str) -> dict:
    with open(f"{FIXTURES_DIR}/{name}", encoding="utf-8") as f:
        return json.load(f)


def test_unexpected_error_retries_then_dead_letters(monkeypatch):
    db = SessionLocal()
    try:
        payload = _load("happy_path.json")["pulseforge"]
        result = ingest_batch(
            db,
            vendor="pulseforge",
            envelope_payload=payload,
            records=payload["events"][:1],
            native_id_field="event_id",
        )
        raw_event = db.execute(
            select(RawEvent).where(RawEvent.batch_id == result.batch_id)
        ).scalars().one()

        def boom(record, asset_lookup):
            raise RuntimeError("simulated transient failure")

        monkeypatch.setitem(normalization_service._NORMALIZERS, "pulseforge", boom)
        asset_lookup = normalization_service.load_asset_lookup(db)

        for expected_retry_count in (1, 2):
            outcome = normalization_service.normalize_raw_event(db, raw_event, asset_lookup)
            assert outcome.status == "pending"
            assert raw_event.retry_count == expected_retry_count

        outcome = normalization_service.normalize_raw_event(db, raw_event, asset_lookup)
        assert outcome.status == "failed"
        assert raw_event.retry_count == 3
        assert raw_event.error_reason == "PROCESSING_ERROR:RuntimeError"
    finally:
        db.close()


def test_normalize_batch_only_touches_its_own_batch():
    db = SessionLocal()
    try:
        payload_a = _load("happy_path.json")["pulseforge"]
        result_a = ingest_batch(
            db,
            vendor="pulseforge",
            envelope_payload=payload_a,
            records=payload_a["events"],
            native_id_field="event_id",
        )

        payload_b = _load("out_of_order.json")["pulseforge"]
        result_b = ingest_batch(
            db,
            vendor="pulseforge",
            envelope_payload=payload_b,
            records=payload_b["events"],
            native_id_field="event_id",
        )

        processing_jobs.normalize_batch(str(result_a.batch_id))

        batch_a_events = db.execute(
            select(RawEvent).where(RawEvent.batch_id == result_a.batch_id)
        ).scalars().all()
        assert all(e.status != "pending" for e in batch_a_events)

        batch_b_events = db.execute(
            select(RawEvent).where(RawEvent.batch_id == result_b.batch_id)
        ).scalars().all()
        assert all(e.status == "pending" for e in batch_b_events)
    finally:
        db.close()


def test_recompute_machine_state_creates_row():
    db = SessionLocal()
    try:
        processing_jobs.recompute_machine_state("EQ-002")
        state = db.get(MachineState, "EQ-002")
        assert state is not None
        assert state.plant_id == "PLANT_01"
        assert state.line_id == "LINE-A"
        assert state.last_processed_at is not None
    finally:
        db.close()
