import json

from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.derivation.service import compute_and_store
from app.ingestion.service import ingest_batch
from app.main import app
from app.normalization.service import normalize_pending_events

client = TestClient(app)
FIXTURES_DIR = "Aurik_Tech_Lead_Assessment_Assets/vendor_api_samples"


def _load(name: str) -> dict:
    with open(f"{FIXTURES_DIR}/{name}", encoding="utf-8") as f:
        return json.load(f)


def test_batch_status_endpoint_reports_dead_letter_reasons():
    db = SessionLocal()
    try:
        payload = _load("malformed.json")["pulseforge"]
        result = ingest_batch(db, "pulseforge", payload, payload["events"], "event_id")
        normalize_pending_events(db)
    finally:
        db.close()

    resp = client.get(f"/v1/ingest/status/{result.batch_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["vendor"] == "pulseforge"
    assert body["total_records"] == 2
    assert body["failed"] == 2
    assert len(body["dead_letters"]) == 2
    reasons = {d["reason"] for d in body["dead_letters"]}
    assert reasons == {"MISSING_MACHINE_ID", "INVALID_FIELD:event_time"}


def test_batch_status_unknown_batch_is_404():
    resp = client.get("/v1/ingest/status/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


def test_batch_status_malformed_batch_id_is_422():
    resp = client.get("/v1/ingest/status/not-a-uuid")
    assert resp.status_code == 422


def _ingest_and_derive_conflicting_updates():
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
        compute_and_store(db, "EQ-008")
    finally:
        db.close()


def test_machine_view_endpoint_reflects_derivation():
    _ingest_and_derive_conflicting_updates()

    resp = client.get("/v1/machines/EQ-008")
    assert resp.status_code == 200
    body = resp.json()
    assert body["derived_status"] == "CRITICAL"
    assert "MAJOR_DEFECT_FOUND" in body["reason_codes"]
    assert body["plant_id"] == "PLANT_02"
    assert body["line_id"] == "LINE-E"


def test_machine_view_unknown_machine_is_404():
    resp = client.get("/v1/machines/EQ-DOES-NOT-EXIST")
    assert resp.status_code == 404


def test_untouched_machine_returns_sane_defaults():
    # EQ-005 is never ingested/normalized/derived by any test, so this
    # exercises the "no data yet" default path (asset exists, no machine_state row).
    resp = client.get("/v1/machines/EQ-005")
    assert resp.status_code == 200
    body = resp.json()
    assert body["derived_status"] == "OK"
    assert body["processing_status"] == "failed"
    assert body["reason_codes"] == []
    assert body["last_processed_at"] is None


def test_list_machines_filters_by_plant_and_status():
    _ingest_and_derive_conflicting_updates()

    resp = client.get("/v1/machines", params={"plant_id": "PLANT_02", "status": "CRITICAL"})
    assert resp.status_code == 200
    body = resp.json()
    assert any(m["machine_id"] == "EQ-008" for m in body)
    assert all(m["plant_id"] == "PLANT_02" and m["derived_status"] == "CRITICAL" for m in body)


def test_plant_and_line_summary_reflect_critical_machine():
    _ingest_and_derive_conflicting_updates()

    resp = client.get("/v1/plants/PLANT_02/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert "EQ-008" in body["critical_machines"]
    assert body["status_counts"]["CRITICAL"] >= 1
    line_e = next(line for line in body["lines"] if line["line_id"] == "LINE-E")
    assert "EQ-008" in line_e["critical_machines"]

    resp = client.get("/v1/lines/LINE-E/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["plant_id"] == "PLANT_02"
    assert "EQ-008" in body["critical_machines"]


def test_plant_summary_unknown_plant_is_404():
    resp = client.get("/v1/plants/PLANT_DOES_NOT_EXIST/summary")
    assert resp.status_code == 404


def test_line_summary_unknown_line_is_404():
    resp = client.get("/v1/lines/LINE_DOES_NOT_EXIST/summary")
    assert resp.status_code == 404
