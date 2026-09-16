from typing import Dict

from app.models.enums import EventCategory
from app.models.reference import AssetReference
from app.normalization.errors import NormalizationError
from app.normalization.machine_resolution import resolve_machine
from app.normalization.result import NormalizedData
from app.normalization.timestamps import parse_epoch_ms

# Cross-vendor canonicalization: ThermexWatch's alert codes map to the same
# canonical event types PulseForge already uses for the equivalent concept.
ALERT_CODE_MAP = {
    "VIB_WARN": (EventCategory.VIBRATION.value, "HIGH_VIBRATION"),
    "TEMP_WARN": (EventCategory.TEMPERATURE.value, "TEMP_SPIKE"),
    "TEMP_CRIT": (EventCategory.TEMPERATURE.value, "TEMP_SPIKE"),
    "POWER_DROP": (EventCategory.POWER.value, "POWER_FLUCTUATION"),
    "OK": (EventCategory.SENSOR_HEALTH.value, "RECOVERY_SIGNAL"),
}

LEVEL_TO_SEVERITY = {1: "info", 2: "low", 3: "medium", 4: "high", 5: "critical"}


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
    machine_id, plant_id, line_id = resolve_machine(record.get("assetCode"), asset_lookup)

    try:
        event_time_utc = parse_epoch_ms(record.get("timestampMs"))
    except ValueError:
        raise NormalizationError("INVALID_FIELD:timestampMs")

    mapping = ALERT_CODE_MAP.get(record.get("alertCode"))
    if mapping is None:
        raise NormalizationError("INVALID_FIELD:alertCode")
    category, event_type_canonical = mapping

    level = record.get("level")
    if isinstance(level, bool) or not isinstance(level, int) or level not in LEVEL_TO_SEVERITY:
        raise NormalizationError("INVALID_FIELD:level")
    severity_canonical = LEVEL_TO_SEVERITY[level]

    flags: list = []
    vibration_g = _safe_float(record, "vibration_g", flags, low=0)
    power_kw = _safe_float(record, "power_kw", flags, low=0)

    temperature_f = record.get("temperature_f")
    temperature_c = None
    if isinstance(temperature_f, (int, float)) and not isinstance(temperature_f, bool):
        temperature_c = (float(temperature_f) - 32.0) * 5.0 / 9.0
    else:
        flags.append("INVALID_TEMPERATURE_F")

    # Note: vibration_g (acceleration) and PulseForge's vibration_mm_s (velocity)
    # are different physical quantities and cannot be converted without knowing
    # vibration frequency, so they're kept as distinct units rather than merged.
    metric_value, metric_unit = None, None
    if category == EventCategory.VIBRATION.value:
        metric_value, metric_unit = vibration_g, "g"
    elif category == EventCategory.TEMPERATURE.value:
        metric_value, metric_unit = temperature_c, "c"
    elif category == EventCategory.POWER.value:
        metric_value, metric_unit = power_kw, "kw"

    return NormalizedData(
        machine_id=machine_id,
        plant_id=plant_id,
        line_id=line_id,
        event_time_utc=event_time_utc,
        category=category,
        event_type_canonical=event_type_canonical,
        severity_canonical=severity_canonical,
        metric_value=metric_value,
        metric_unit_canonical=metric_unit,
        extra={
            "is_active": record.get("is_active"),
            "signal_quality": record.get("signal_quality"),
            "vibration_g": vibration_g,
            "temperature_c": temperature_c,
            "power_kw": power_kw,
            "data_quality_flags": flags,
        },
    )
