from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from app.db.session import Base


class MachineState(Base):
    """Materialized, derived attention view for a machine (one row per machine)."""

    __tablename__ = "machine_state"

    machine_id = Column(String, ForeignKey("asset_reference.machine_id"), primary_key=True)
    plant_id = Column(String, nullable=False, index=True)
    line_id = Column(String, nullable=False, index=True)

    derived_status = Column(String, nullable=False, index=True)
    attention_level = Column(Integer, nullable=False)
    reason_codes = Column(JSONB, nullable=False, default=list)

    latest_relevant_event_time = Column(DateTime(timezone=True), nullable=True)
    processing_status = Column(String, nullable=False)
    source_event_refs = Column(JSONB, nullable=False, default=list)

    last_processed_at = Column(DateTime(timezone=True), nullable=True)
