import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


class NormalizedEvent(Base):
    """Canonical representation of a raw vendor event/record."""

    __tablename__ = "normalized_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_event_id = Column(
        UUID(as_uuid=True), ForeignKey("raw_events.id"), nullable=False, unique=True, index=True
    )
    vendor = Column(String, nullable=False, index=True)

    machine_id = Column(String, ForeignKey("asset_reference.machine_id"), nullable=False, index=True)
    plant_id = Column(String, nullable=False, index=True)
    line_id = Column(String, nullable=False, index=True)

    event_time_utc = Column(DateTime(timezone=True), nullable=False, index=True)
    category = Column(String, nullable=False, index=True)
    event_type_canonical = Column(String, nullable=False)
    severity_canonical = Column(String, nullable=False)

    metric_value = Column(Float, nullable=True)
    metric_unit_canonical = Column(String, nullable=True)

    # Vendor-specific qualitative fields that don't fit the numeric metric shape
    # (e.g. technician_note, maintenance_status, inspection_result, confidence).
    extra = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    raw_event = relationship("RawEvent")
