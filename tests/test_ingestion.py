import json

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)

FIXTURES_DIR = "Aurik_Tech_Lead_Assessment_Assets/vendor_api_samples"


def _load(name: str) -> dict:
    with open(f"{FIXTURES_DIR}/{name}", encoding="utf-8") as f:
        return json.load(f)


def test_ingest_pulseforge_happy_path():
    payload = _load("pulseforge_sample.json")
    response = client.post(
        "/v1/ingest/pulseforge",
        json=payload,
        headers={"X-Vendor-Key": settings.pulseforge_api_key},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["vendor"] == "pulseforge"
    assert body["total_records"] == 2
    assert body["accepted"] + body["duplicates"] == 2


def test_ingest_rejects_wrong_vendor_key():
    payload = _load("pulseforge_sample.json")
    response = client.post(
        "/v1/ingest/pulseforge",
        json=payload,
        headers={"X-Vendor-Key": "wrong-key"},
    )
    assert response.status_code == 401


def test_ingest_rejects_malformed_envelope():
    response = client.post(
        "/v1/ingest/pulseforge",
        json={"vendor": "PulseForge"},  # missing required "events" field
        headers={"X-Vendor-Key": settings.pulseforge_api_key},
    )
    assert response.status_code == 422


def test_ingest_duplicates_are_noop_on_repeat_post():
    payload = _load("duplicates.json")["pulseforge"]

    first = client.post(
        "/v1/ingest/pulseforge",
        json=payload,
        headers={"X-Vendor-Key": settings.pulseforge_api_key},
    ).json()
    # PF-1001 was already ingested by the happy-path test (same event_id
    # appears in both pulseforge_sample.json and duplicates.json by design),
    # and this fixture also repeats it twice within its own batch — so
    # every occurrence here should register as a duplicate.
    assert first["accepted"] == 0
    assert first["duplicates"] == 2

    second = client.post(
        "/v1/ingest/pulseforge",
        json=payload,
        headers={"X-Vendor-Key": settings.pulseforge_api_key},
    ).json()
    assert second["accepted"] == 0
    assert second["duplicates"] == 2


def test_ingest_thermexwatch_happy_path():
    payload = _load("thermexwatch_sample.json")
    response = client.post(
        "/v1/ingest/thermexwatch",
        json=payload,
        headers={"X-Vendor-Key": settings.thermexwatch_api_key},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["vendor"] == "thermexwatch"
    assert body["total_records"] == 2


def test_ingest_maintaflow_happy_path():
    payload = _load("maintaflow_sample.json")
    response = client.post(
        "/v1/ingest/maintaflow",
        json=payload,
        headers={"X-Vendor-Key": settings.maintaflow_api_key},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["vendor"] == "maintaflow"
    assert body["total_records"] == 2


def test_ingest_missing_native_id_is_stored_as_rejected_not_dropped():
    payload = {
        "provider_name": "MaintaFlow",
        "factory_id": "PLANT_01",
        "records": [
            {
                # no record_id at all — should be rejected, not silently dropped
                "machine_ref": "EQ-001",
                "line_ref": "LINE-A",
                "recorded_at": "2026/04/18 09:00:00",
                "record_type": "operator_note",
            }
        ],
    }
    response = client.post(
        "/v1/ingest/maintaflow",
        json=payload,
        headers={"X-Vendor-Key": settings.maintaflow_api_key},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["total_records"] == 1
    assert body["rejected"] == 1
    assert body["accepted"] == 0
