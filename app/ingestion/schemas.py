from typing import Any, Dict, List

from pydantic import BaseModel


class PulseForgeEnvelope(BaseModel):
    vendor: str
    plant_id: str
    batch_generated_at: str
    events: List[Dict[str, Any]]


class ThermexWatchEnvelope(BaseModel):
    source: str
    site_code: str
    response_time_epoch_ms: int
    readings: List[Dict[str, Any]]


class MaintaFlowEnvelope(BaseModel):
    provider_name: str
    factory_id: str
    records: List[Dict[str, Any]]


class IngestResponse(BaseModel):
    batch_id: str
    vendor: str
    total_records: int
    accepted: int
    duplicates: int
    rejected: int
