from typing import Dict

from app.models.enums import EventCategory
from app.models.reference import AssetReference
from app.normalization.errors import NormalizationError
from app.normalization.machine_resolution import resolve_machine
from app.normalization.result import NormalizedData
from app.normalization.timestamps import parse_maintaflow_datetime

RECORD_TYPE_MAP = {
    "inspection": (EventCategory.INSPECTION.value, "INSPECTION"),
    "maintenance_update": (EventCategory.MAINTENANCE.value, "MAINTENANCE_UPDATE"),
    "operator_note": (EventCategory.NOTE.value, "OPERATOR_NOTE"),
    "calibration": (EventCategory.MAINTENANCE.value, "CALIBRATION"),
}


def _derive_severity(inspection_result, maintenance_status) -> str:
    """Deterministic, explainable severity heuristic for qualitative MaintaFlow
    records — there's no vendor-supplied severity field, unlike the sensor
    vendors, so this is our own judgment call rather than a vendor mapping."""
    if inspection_result == "major_defect_found":
        return "critical"
    if maintenance_status == "overdue":
        return "high"
    if inspection_result == "minor_defect_found":
        return "medium"
    return "info"


def normalize(record: dict, asset_lookup: Dict[str, AssetReference]) -> NormalizedData:
    machine_id, plant_id, line_id = resolve_machine(record.get("machine_ref"), asset_lookup)

    try:
        event_time_utc = parse_maintaflow_datetime(record.get("recorded_at"))
    except ValueError:
        raise NormalizationError("INVALID_FIELD:recorded_at")

    mapping = RECORD_TYPE_MAP.get(record.get("record_type"))
    if mapping is None:
        raise NormalizationError("INVALID_FIELD:record_type")
    category, event_type_canonical = mapping

    inspection_result = record.get("inspection_result")
    maintenance_status = record.get("maintenance_status")
    days_since_last_service = record.get("days_since_last_service")

    severity_canonical = _derive_severity(inspection_result, maintenance_status)

    metric_value, metric_unit = None, None
    if isinstance(days_since_last_service, (int, float)) and not isinstance(days_since_last_service, bool):
        metric_value, metric_unit = float(days_since_last_service), "days_since_service"

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
            "inspection_result": inspection_result,
            "maintenance_status": maintenance_status,
            "days_since_last_service": days_since_last_service,
            "technician_note": record.get("technician_note"),
            "manual_confidence": record.get("manual_confidence"),
        },
    )
