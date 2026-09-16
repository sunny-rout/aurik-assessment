from datetime import datetime, timedelta
from typing import Dict, Optional

from app.derivation.result import DerivationResult
from app.models.enums import EventCategory
from app.models.reference import AssetReference

SEVERITY_TO_LEVEL = {"info": 1, "low": 2, "medium": 3, "high": 4, "critical": 5}
LEVEL_TO_STATUS = {1: "OK", 2: "WATCH", 3: "WATCH", 4: "ATTENTION", 5: "CRITICAL"}

LOW_SENSOR_CONFIDENCE_THRESHOLD = 0.5

# How long a machine can go without a fresh signal before it's considered
# stale. Note: staleness is measured against the dataset's own clock (the
# latest event_time_utc seen anywhere), not real wall-clock time — see
# get_dataset_now() in service.py. This is deliberate: the sample data is a
# fixed historical batch, so comparing against actual "now" would mark every
# machine stale regardless of the data's own internal freshness.
STALENESS_THRESHOLD = timedelta(hours=2)


def evaluate_machine(
    asset: AssetReference,
    latest_by_category: Dict[str, object],
    dataset_now: datetime,
) -> DerivationResult:
    """Deterministic rule engine producing a machine's attention view.

    `latest_by_category` must already reflect the true latest reading per
    category by event_time_utc (not receipt order) — see
    service.get_latest_by_category(), which is what makes this resilient to
    out-of-order or conflicting vendor updates.
    """
    reason_codes: list = []
    attention_level = 1
    latest_relevant_event_time: Optional[datetime] = None
    source_event_refs: list = []

    def bump(level: int, reason: str) -> None:
        nonlocal attention_level
        if reason not in reason_codes:
            reason_codes.append(reason)
        attention_level = max(attention_level, level)

    for category, event in latest_by_category.items():
        if event is None:
            continue

        source_event_refs.append(str(event.raw_event_id))
        if latest_relevant_event_time is None or event.event_time_utc > latest_relevant_event_time:
            latest_relevant_event_time = event.event_time_utc

        vendor_level = SEVERITY_TO_LEVEL.get(event.severity_canonical, 1)
        if event.severity_canonical == "critical":
            bump(vendor_level, "VENDOR_CRITICAL_ALERT")
        elif event.severity_canonical == "high":
            bump(vendor_level, "VENDOR_HIGH_ALERT")
        else:
            attention_level = max(attention_level, vendor_level)

        if (
            category == EventCategory.TEMPERATURE.value
            and event.metric_unit_canonical == "c"
            and event.metric_value is not None
            and asset.rated_max_temp_c is not None
            and event.metric_value > asset.rated_max_temp_c
        ):
            bump(4, "TEMP_ABOVE_RATED")

        if (
            category == EventCategory.VIBRATION.value
            and event.metric_unit_canonical == "mm_s"
            and event.metric_value is not None
            and asset.rated_max_vibration_mm_s is not None
            and event.metric_value > asset.rated_max_vibration_mm_s
        ):
            bump(4, "VIB_ABOVE_RATED")
        # Note: ThermexWatch's vibration_g has no rated threshold in
        # asset_reference (different physical unit — see Phase 3), so it can
        # only escalate via its own vendor-reported severity above.

        if (
            category == EventCategory.SENSOR_HEALTH.value
            and event.metric_value is not None
            and event.metric_value < LOW_SENSOR_CONFIDENCE_THRESHOLD
        ):
            bump(3, "LOW_SENSOR_CONFIDENCE")

        if category in (EventCategory.MAINTENANCE.value, EventCategory.INSPECTION.value):
            extra = event.extra or {}
            if extra.get("maintenance_status") == "overdue":
                bump(4, "MAINTENANCE_OVERDUE")
            if extra.get("inspection_result") == "major_defect_found":
                bump(5, "MAJOR_DEFECT_FOUND")
            elif extra.get("inspection_result") == "minor_defect_found":
                bump(3, "MINOR_DEFECT_FOUND")

    derived_status = LEVEL_TO_STATUS[attention_level]

    # High-criticality assets are escalated one notch at the ATTENTION
    # boundary — the same reading matters more on equipment we can least
    # afford to lose.
    if derived_status == "ATTENTION" and asset.criticality == "high":
        attention_level = 5
        derived_status = "CRITICAL"
        reason_codes.append("HIGH_CRITICALITY_ESCALATION")

    if latest_relevant_event_time is None:
        processing_status = "failed"
    elif dataset_now - latest_relevant_event_time > STALENESS_THRESHOLD:
        processing_status = "stale"
    else:
        processing_status = "ok"

    return DerivationResult(
        derived_status=derived_status,
        attention_level=attention_level,
        reason_codes=reason_codes,
        latest_relevant_event_time=latest_relevant_event_time,
        processing_status=processing_status,
        source_event_refs=source_event_refs,
    )
