from typing import Dict

from app.models.enums import EventCategory, SeverityLevel
from app.models.reference import AssetReference
from app.normalization.errors import NormalizationError
from app.normalization.machine_resolution import resolve_machine
from app.normalization.result import NormalizedData
from app.normalization.timestamps import parse_iso8601

EVENT_TYPE_MAP = {
    "HIGH_VIBRATION": (EventCategory.VIBRATION.value, "HIGH_VIBRATION"),
    "TEMP_SPIKE": (EventCategory.TEMPERATURE.value, "TEMP_SPIKE"),
    "SENSOR_HEALTH_DROP": (EventCategory.SENSOR_HEALTH.value, "SENSOR_HEALTH_DROP"),
    "POWER_FLUCTUATION": (EventCategory.POWER.value, "POWER_FLUCTUATION"),
    "RECOVERY_SIGNAL": (EventCategory.SENSOR_HEALTH.value, "RECOVERY_SIGNAL"),
}

VALID_SEVERITIES = {s.value for s in SeverityLevel}


def _safe_float(record: dict, key: str, flags: list, low=None, high=None):
    value = record.get(key)
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        flags.append(f"INVALID_{key.upper()}")
        return None
    if (low is not None and parsed < low) or (high is not None and parsed > high):
        flags.append(f"{key.upper()}_OUT_OF_RANGE")
        return None
    return parsed


def normalize(record: dict, asset_lookup: Dict[str, AssetReference]) -> NormalizedData:
    machine_id, plant_id, line_id = resolve_machine(record.get("machine_id"), asset_lookup)

    try:
        event_time_utc = parse_iso8601(record.get("event_time"))
    except ValueError:
        raise NormalizationError("INVALID_FIELD:event_time")

    mapping = EVENT_TYPE_MAP.get(record.get("event_type"))
    if mapping is None:
        raise NormalizationError("INVALID_FIELD:event_type")
    category, event_type_canonical = mapping

    severity = record.get("severity")
    if severity not in VALID_SEVERITIES:
        raise NormalizationError("INVALID_FIELD:severity")

    flags: list = []
    vibration_mm_s = _safe_float(record, "vibration_mm_s", flags, low=0)
    temperature_c = _safe_float(record, "temperature_c", flags, low=-273.15)
    sensor_health = _safe_float(record, "sensor_health", flags, low=0, high=1)
    vendor_confidence = _safe_float(record, "vendor_confidence", flags, low=0, high=1)

    metric_value, metric_unit = None, None
    if category == EventCategory.VIBRATION.value:
        metric_value, metric_unit = vibration_mm_s, "mm_s"
    elif category == EventCategory.TEMPERATURE.value:
        metric_value, metric_unit = temperature_c, "c"
    elif category == EventCategory.SENSOR_HEALTH.value:
        metric_value, metric_unit = sensor_health, "ratio"
    # POWER category (POWER_FLUCTUATION) has no dedicated field in PulseForge
    # payloads in this dataset — metric stays None, raw fields are still kept below.

    return NormalizedData(
        machine_id=machine_id,
        plant_id=plant_id,
        line_id=line_id,
        event_time_utc=event_time_utc,
        category=category,
        event_type_canonical=event_type_canonical,
        severity_canonical=severity,
        metric_value=metric_value,
        metric_unit_canonical=metric_unit,
        extra={
            "machine_state": record.get("machine_state"),
            "vibration_mm_s": vibration_mm_s,
            "temperature_c": temperature_c,
            "sensor_health": sensor_health,
            "vendor_confidence": vendor_confidence,
            "data_quality_flags": flags,
        },
    )
