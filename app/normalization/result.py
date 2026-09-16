from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class NormalizedData:
    machine_id: str
    plant_id: str
    line_id: str
    event_time_utc: datetime
    category: str
    event_type_canonical: str
    severity_canonical: str
    metric_value: Optional[float]
    metric_unit_canonical: Optional[str]
    extra: Dict[str, Any] = field(default_factory=dict)
