import json

from app.db.session import SessionLocal
from app.derivation.service import compute_and_store
from app.ingestion.service import ingest_batch
from app.normalization.service import normalize_pending_events

FIXTURES_DIR = "Aurik_Tech_Lead_Assessment_Assets/vendor_api_samples"


def _load(name: str) -> dict:
    with open(f"{FIXTURES_DIR}/{name}", encoding="utf-8") as f:
        return json.load(f)


def test_conflicting_updates_across_vendors_drive_machine_critical():
    """EQ-008 (PLANT_02, rated_max_temp_c=92.0) gets a low-severity PulseForge
    recovery reading, a critical ThermexWatch temp alert (201F=93.9C, above
    rated), and a MaintaFlow major-defect inspection — all pointing the same
    way, so the derived state should clearly reflect CRITICAL with multiple
    corroborating reasons."""
    db = SessionLocal()
    try:
        fixture = _load("conflicting_updates.json")

        pf = fixture["pulseforge"]
        ingest_batch(db, "pulseforge", pf, pf["events"], "event_id")

        tw = fixture["thermexwatch"]
        ingest_batch(db, "thermexwatch", tw, tw["readings"], "readingId")

        mf = fixture["maintaflow"]
        ingest_batch(db, "maintaflow", mf, mf["records"], "record_id")

        normalize_pending_events(db)
        result = compute_and_store(db, "EQ-008")

        assert result.derived_status == "CRITICAL"
        assert "VENDOR_CRITICAL_ALERT" in result.reason_codes
        assert "TEMP_ABOVE_RATED" in result.reason_codes
        assert "MAJOR_DEFECT_FOUND" in result.reason_codes
    finally:
        db.close()


def test_out_of_order_receipt_does_not_override_chronologically_later_event():
    """Ingests a chronologically LATER, low-severity vibration reading BEFORE
    a chronologically EARLIER, high-severity vibration warning — same
    machine, same category (both alertCode=VIB_WARN), so they genuinely
    compete for the "latest vibration reading" slot. Since real-world
    delivery order isn't guaranteed, the derived state must reflect the
    later event_time_utc, not receipt order — the earlier warning should not
    override the later, calmer reading, even though it was ingested second."""
    db = SessionLocal()
    try:
        later_calm_reading = {
            "readingId": "TW-ORDER-LATE",
            "assetCode": "EQ-006",
            "productionLine": "D",
            "timestampMs": 1776500200000,  # later
            "alertCode": "VIB_WARN",
            "level": 1,
            "vibration_g": 0.1,
            "temperature_f": 130.0,
            "power_kw": 10.0,
            "is_active": True,
            "signal_quality": "GOOD",
        }
        earlier_warning_reading = {
            "readingId": "TW-ORDER-EARLY",
            "assetCode": "EQ-006",
            "productionLine": "D",
            "timestampMs": 1776500100000,  # earlier, but received second
            "alertCode": "VIB_WARN",
            "level": 4,
            "vibration_g": 0.9,
            "temperature_f": 130.0,
            "power_kw": 10.0,
            "is_active": True,
            "signal_quality": "GOOD",
        }
        envelope = {
            "source": "ThermexWatch",
            "site_code": "PLANT_02",
            "response_time_epoch_ms": 1776500300000,
            "readings": [later_calm_reading, earlier_warning_reading],
        }

        ingest_batch(db, "thermexwatch", envelope, envelope["readings"], "readingId")
        normalize_pending_events(db)
        result = compute_and_store(db, "EQ-006")

        # the later, calmer reading should win for the vibration picture,
        # not the earlier warning that happened to be processed second.
        assert "VENDOR_HIGH_ALERT" not in result.reason_codes
        assert result.derived_status in ("OK", "WATCH")
    finally:
        db.close()
