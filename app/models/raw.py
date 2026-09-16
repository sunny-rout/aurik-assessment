import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.session import Base
from app.models.enums import RawEventStatus


class RawBatch(Base):
    """One vendor ingestion request, stored verbatim for traceability."""

    __tablename__ = "raw_batches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendor = Column(String, nullable=False, index=True)
    raw_payload = Column(JSONB, nullable=False)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    events = relationship("RawEvent", back_populates="batch")


class RawEvent(Base):
    """One vendor record within a batch, tracked through normalization."""

    __tablename__ = "raw_events"
    __table_args__ = (
        UniqueConstraint("vendor", "native_event_id", name="uq_raw_events_vendor_native_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id = Column(UUID(as_uuid=True), ForeignKey("raw_batches.id"), nullable=False, index=True)
    vendor = Column(String, nullable=False, index=True)
    native_event_id = Column(String, nullable=False)
    raw_record = Column(JSONB, nullable=False)
    status = Column(String, nullable=False, default=RawEventStatus.PENDING.value, index=True)
    error_reason = Column(String, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    batch = relationship("RawBatch", back_populates="events")
