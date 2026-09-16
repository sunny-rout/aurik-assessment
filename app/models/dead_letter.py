import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.session import Base


class DeadLetterEvent(Base):
    """Raw events that failed normalization and won't be retried automatically."""

    __tablename__ = "dead_letter_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    raw_event_id = Column(UUID(as_uuid=True), ForeignKey("raw_events.id"), nullable=False, index=True)
    vendor = Column(String, nullable=False, index=True)
    reason = Column(String, nullable=False)
    raw_record = Column(JSONB, nullable=False)
    retry_count = Column(Integer, nullable=False, default=0)
    failed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
