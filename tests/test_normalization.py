import json
from types import SimpleNamespace

import pytest

from app.normalization import maintaflow, pulseforge, thermexwatch
from app.normalization.errors import NormalizationError

FIXTURES_DIR = "Aurik_Tech_Lead_Assessment_Assets/vendor_api_samples"

# Mirrors asset_reference.csv without needing a live DB for these pure unit tests.
ASSET_LOOKUP = {
    "EQ-001": SimpleNamespace(machine_id="EQ-001", plant_id="PLANT_01", line_id="LINE-A"),
    "EQ-002": SimpleNamespace(machine_id="EQ-002", plant_id="PLANT_01", line_id="LINE-A"),
    "EQ-003": SimpleNamespace(machine_id="EQ-003", plant_id="PLANT_01", line_id="LINE-B"),
    "EQ-004": SimpleNamespace(machine_id="EQ-004", plant_id="PLANT_01", line_id="LINE-C"),
    "EQ-005": SimpleNamespace(machine_id="EQ-005", plant_id="PLANT_02", line_id="LINE-D"),
    "EQ-006": SimpleNamespace(machine_id="EQ-006", plant_id="PLANT_02", line_id="LINE-D"),
    "EQ-007": SimpleNamespace(machine_id="EQ-007", plant_id="PLANT_02", line_id="LINE-E"),
    "EQ-008": SimpleNamespace(machine_id="EQ-008", plant_id="PLANT_02", line_id="LINE-E"),
}


def _load(name: str) -> dict:
    with open(f"{FIXTURES_DIR}/{name}", encoding="utf-8") as f:
        return json.load(f)


# --- PulseForge ---------------------------------------------------------


def test_pulseforge_happy_path_normalizes():
    events = _load("happy_path.json")["pulseforge"]["events"]
    result = pulseforge.normalize(events[0], ASSET_LOOKUP)
    assert result.machine_id == "EQ-001"
    assert result.plant_id == "PLANT_01"
    assert result.category == "vibration"
    assert result.severity_canonical == "medium"
    assert result.metric_value == 9.8
    assert result.metric_unit_canonical == "mm_s"


def test_pulseforge_missing_machine_id_fails():
    record = _load("malformed.json")["pulseforge"]["events"][0]  # machine_id ""
    with pytest.raises(NormalizationError) as exc:
        pulseforge.normalize(record, ASSET_LOOKUP)
    assert exc.value.reason == "MISSING_MACHINE_ID"


def test_pulseforge_invalid_timestamp_fails():
    record = _load("malformed.json")["pulseforge"]["events"][1]  # bad event_time
    with pytest.raises(NormalizationError) as exc:
        pulseforge.normalize(record, ASSET_LOOKUP)
    assert exc.value.reason == "INVALID_FIELD:event_time"


def test_pulseforge_unknown_machine_fails():
    record = {**_load("happy_path.json")["pulseforge"]["events"][0], "machine_id": "EQ-999"}
    with pytest.raises(NormalizationError) as exc:
        pulseforge.normalize(record, ASSET_LOOKUP)
    assert exc.value.reason == "UNKNOWN_ASSET"


# --- ThermexWatch --------------------------------------------------------


def test_thermexwatch_happy_path_normalizes():
    reading = _load("happy_path.json")["thermexwatch"]["readings"][0]  # VIB_WARN, level 3
    result = thermexwatch.normalize(reading, ASSET_LOOKUP)
    assert result.machine_id == "EQ-005"
    assert result.category == "vibration"
    assert result.severity_canonical == "medium"
    assert result.metric_unit_canonical == "g"


def test_thermexwatch_temperature_converted_to_celsius():
    reading = _load("happy_path.json")["thermexwatch"]["readings"][1]  # temperature_f 132.0
    result = thermexwatch.normalize(reading, ASSET_LOOKUP)
    assert abs(result.extra["temperature_c"] - 55.5556) < 0.01


def test_thermexwatch_missing_machine_id_fails():
    record = _load("malformed.json")["thermexwatch"]["readings"][0]  # assetCode null
    with pytest.raises(NormalizationError) as exc:
        thermexwatch.normalize(record, ASSET_LOOKUP)
    assert exc.value.reason == "MISSING_MACHINE_ID"


def test_thermexwatch_unknown_alert_code_fails():
    record = _load("malformed.json")["thermexwatch"]["readings"][1]  # alertCode UNKNOWN_ALERT
    with pytest.raises(NormalizationError) as exc:
        thermexwatch.normalize(record, ASSET_LOOKUP)
    assert exc.value.reason == "INVALID_FIELD:alertCode"


# --- MaintaFlow ------------------------------------------------------------


def test_maintaflow_happy_path_normalizes():
    record = _load("happy_path.json")["maintaflow"]["records"][0]
    result = maintaflow.normalize(record, ASSET_LOOKUP)
    assert result.machine_id == "EQ-005"
    assert result.category == "inspection"
    assert result.severity_canonical == "info"


def test_maintaflow_major_defect_is_critical_severity():
    record = _load("conflicting_updates.json")["maintaflow"]["records"][0]
    result = maintaflow.normalize(record, ASSET_LOOKUP)
    assert result.severity_canonical == "critical"


def test_maintaflow_overdue_maintenance_is_high_severity():
    record = _load("retry_cases.json")["maintaflow"]["records"][0]
    result = maintaflow.normalize(record, ASSET_LOOKUP)
    assert result.severity_canonical == "high"


def test_maintaflow_missing_machine_id_fails():
    record = _load("retry_cases.json")["maintaflow"]["records"][1]  # machine_ref ""
    with pytest.raises(NormalizationError) as exc:
        maintaflow.normalize(record, ASSET_LOOKUP)
    assert exc.value.reason == "MISSING_MACHINE_ID"
