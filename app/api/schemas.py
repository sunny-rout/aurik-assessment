from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel


class MachineView(BaseModel):
    machine_id: str
    plant_id: str
    line_id: str
    criticality: str
    derived_status: str
    attention_level: int
    reason_codes: List[str]
    latest_relevant_event_time: Optional[datetime]
    processing_status: str
    source_event_refs: List[str]
    last_processed_at: Optional[datetime]


class DeadLetterInfo(BaseModel):
    raw_event_id: str
    native_event_id: str
    reason: str


class BatchStatusResponse(BaseModel):
    batch_id: str
    vendor: str
    received_at: datetime
    total_records: int
    pending: int
    normalized: int
    failed: int
    dead_letters: List[DeadLetterInfo]


class LineSummary(BaseModel):
    line_id: str
    line_name: str
    plant_id: str
    total_machines: int
    status_counts: Dict[str, int]
    critical_machines: List[str]
    stale_count: int
    failed_count: int


class PlantSummary(BaseModel):
    plant_id: str
    total_machines: int
    status_counts: Dict[str, int]
    critical_machines: List[str]
    stale_count: int
    failed_count: int
    lines: List[LineSummary]
