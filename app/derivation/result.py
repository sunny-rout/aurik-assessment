from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class DerivationResult:
    derived_status: str
    attention_level: int
    reason_codes: List[str]
    latest_relevant_event_time: Optional[datetime]
    processing_status: str
    source_event_refs: List[str] = field(default_factory=list)
