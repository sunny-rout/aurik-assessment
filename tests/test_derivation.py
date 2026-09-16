import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.derivation.rules import evaluate_machine

ASSET = SimpleNamespace(
    machine_id="EQ-001",
    plant_id="PLANT_01",
    line_id="LINE-A",
    criticality="medium",
    rated_max_temp_c=85.0,
    rated_max_vibration_mm_s=9.0,
)

HIGH_CRITICALITY_ASSET = SimpleNamespace(**{**ASSET.__dict__, "criticality": "high"})

BASE_TIME = datetime(2026, 4, 18, 8, 0, tzinfo=timezone.utc)


def _event(category, severity="info", value=None, unit=None, extra=None, at=BASE_TIME):
    return SimpleNamespace(
        category=category,
        severity_canonical=severity,
        metric_value=value,
        metric_unit_canonical=unit,
        extra=extra or {},
        event_time_utc=at,
        raw_event_id=uuid.uuid4(),
    )


def test_no_signals_means_ok_but_processing_failed():
    result = evaluate_machine(ASSET, {}, dataset_now=BASE_TIME)
    assert result.derived_status == "OK"
    assert result.attention_level == 1
    assert result.processing_status == "failed"


def test_temperature_above_rated_triggers_attention():
    events = {"temperature": _event("temperature", severity="medium", value=90.0, unit="c")}
    result = evaluate_machine(ASSET, events, dataset_now=BASE_TIME)
    assert "TEMP_ABOVE_RATED" in result.reason_codes
    assert result.derived_status == "ATTENTION"


def test_high_criticality_escalates_attention_to_critical():
    events = {"temperature": _event("temperature", severity="medium", value=90.0, unit="c")}
    result = evaluate_machine(HIGH_CRITICALITY_ASSET, events, dataset_now=BASE_TIME)
    assert result.derived_status == "CRITICAL"
    assert "HIGH_CRITICALITY_ESCALATION" in result.reason_codes


def test_vendor_critical_alert_drives_critical_status():
    events = {"vibration": _event("vibration", severity="critical", value=5.0, unit="g")}
    result = evaluate_machine(ASSET, events, dataset_now=BASE_TIME)
    assert result.derived_status == "CRITICAL"
    assert "VENDOR_CRITICAL_ALERT" in result.reason_codes


def test_maintenance_overdue_triggers_attention():
    events = {
        "maintenance": _event(
            "maintenance", severity="info", extra={"maintenance_status": "overdue"}
        )
    }
    result = evaluate_machine(ASSET, events, dataset_now=BASE_TIME)
    assert "MAINTENANCE_OVERDUE" in result.reason_codes
    assert result.derived_status == "ATTENTION"


def test_major_defect_found_triggers_critical():
    events = {
        "inspection": _event(
            "inspection", severity="info", extra={"inspection_result": "major_defect_found"}
        )
    }
    result = evaluate_machine(ASSET, events, dataset_now=BASE_TIME)
    assert "MAJOR_DEFECT_FOUND" in result.reason_codes
    assert result.derived_status == "CRITICAL"


def test_low_sensor_confidence_triggers_watch():
    events = {"sensor_health": _event("sensor_health", severity="info", value=0.3, unit="ratio")}
    result = evaluate_machine(ASSET, events, dataset_now=BASE_TIME)
    assert "LOW_SENSOR_CONFIDENCE" in result.reason_codes
    assert result.derived_status == "WATCH"


def test_stale_when_latest_event_far_before_dataset_now():
    events = {"temperature": _event("temperature", severity="low", value=70.0, unit="c", at=BASE_TIME)}
    result = evaluate_machine(ASSET, events, dataset_now=BASE_TIME + timedelta(hours=5))
    assert result.processing_status == "stale"


def test_ok_when_latest_event_within_staleness_window():
    events = {"temperature": _event("temperature", severity="low", value=70.0, unit="c", at=BASE_TIME)}
    result = evaluate_machine(ASSET, events, dataset_now=BASE_TIME + timedelta(minutes=30))
    assert result.processing_status == "ok"


def test_vibration_g_unit_does_not_trigger_rated_threshold_rule():
    # ThermexWatch's g-unit vibration has no rated threshold to compare
    # against (different physical quantity than PulseForge's mm_s) — even a
    # numerically large g reading shouldn't trigger VIB_ABOVE_RATED.
    events = {"vibration": _event("vibration", severity="low", value=50.0, unit="g")}
    result = evaluate_machine(ASSET, events, dataset_now=BASE_TIME)
    assert "VIB_ABOVE_RATED" not in result.reason_codes
