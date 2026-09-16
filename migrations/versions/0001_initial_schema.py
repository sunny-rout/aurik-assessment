"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_reference",
        sa.Column("machine_id", sa.String(), primary_key=True),
        sa.Column("plant_id", sa.String(), nullable=False),
        sa.Column("line_id", sa.String(), nullable=False),
        sa.Column("machine_type", sa.String(), nullable=False),
        sa.Column("criticality", sa.String(), nullable=False),
        sa.Column("installed_date", sa.Date(), nullable=True),
        sa.Column("rated_max_temp_c", sa.Float(), nullable=True),
        sa.Column("rated_max_vibration_mm_s", sa.Float(), nullable=True),
        sa.Column("baseline_power_kw", sa.Float(), nullable=True),
        sa.Column("asset_status", sa.String(), nullable=False),
    )
    op.create_index("ix_asset_reference_plant_id", "asset_reference", ["plant_id"])
    op.create_index("ix_asset_reference_line_id", "asset_reference", ["line_id"])

    op.create_table(
        "line_reference",
        sa.Column("line_id", sa.String(), primary_key=True),
        sa.Column("plant_id", sa.String(), nullable=False),
        sa.Column("line_name", sa.String(), nullable=False),
        sa.Column("operating_window", sa.String(), nullable=False),
    )
    op.create_index("ix_line_reference_plant_id", "line_reference", ["plant_id"])

    op.create_table(
        "raw_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vendor", sa.String(), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_raw_batches_vendor", "raw_batches", ["vendor"])

    op.create_table(
        "raw_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("raw_batches.id"), nullable=False),
        sa.Column("vendor", sa.String(), nullable=False),
        sa.Column("native_event_id", sa.String(), nullable=False),
        sa.Column("raw_record", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("error_reason", sa.String(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("vendor", "native_event_id", name="uq_raw_events_vendor_native_id"),
    )
    op.create_index("ix_raw_events_batch_id", "raw_events", ["batch_id"])
    op.create_index("ix_raw_events_vendor", "raw_events", ["vendor"])
    op.create_index("ix_raw_events_status", "raw_events", ["status"])

    op.create_table(
        "normalized_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "raw_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("raw_events.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("vendor", sa.String(), nullable=False),
        sa.Column("machine_id", sa.String(), sa.ForeignKey("asset_reference.machine_id"), nullable=False),
        sa.Column("plant_id", sa.String(), nullable=False),
        sa.Column("line_id", sa.String(), nullable=False),
        sa.Column("event_time_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("event_type_canonical", sa.String(), nullable=False),
        sa.Column("severity_canonical", sa.String(), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("metric_unit_canonical", sa.String(), nullable=True),
        sa.Column("extra", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_normalized_events_vendor", "normalized_events", ["vendor"])
    op.create_index("ix_normalized_events_machine_id", "normalized_events", ["machine_id"])
    op.create_index("ix_normalized_events_plant_id", "normalized_events", ["plant_id"])
    op.create_index("ix_normalized_events_line_id", "normalized_events", ["line_id"])
    op.create_index("ix_normalized_events_event_time_utc", "normalized_events", ["event_time_utc"])
    op.create_index("ix_normalized_events_category", "normalized_events", ["category"])

    op.create_table(
        "machine_state",
        sa.Column("machine_id", sa.String(), sa.ForeignKey("asset_reference.machine_id"), primary_key=True),
        sa.Column("plant_id", sa.String(), nullable=False),
        sa.Column("line_id", sa.String(), nullable=False),
        sa.Column("derived_status", sa.String(), nullable=False),
        sa.Column("attention_level", sa.Integer(), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("latest_relevant_event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_status", sa.String(), nullable=False),
        sa.Column("source_event_refs", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("last_processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_machine_state_plant_id", "machine_state", ["plant_id"])
    op.create_index("ix_machine_state_line_id", "machine_state", ["line_id"])
    op.create_index("ix_machine_state_derived_status", "machine_state", ["derived_status"])

    op.create_table(
        "dead_letter_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("raw_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("raw_events.id"), nullable=False),
        sa.Column("vendor", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("raw_record", postgresql.JSONB(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_dead_letter_events_raw_event_id", "dead_letter_events", ["raw_event_id"])
    op.create_index("ix_dead_letter_events_vendor", "dead_letter_events", ["vendor"])


def downgrade() -> None:
    op.drop_table("dead_letter_events")
    op.drop_table("machine_state")
    op.drop_table("normalized_events")
    op.drop_table("raw_events")
    op.drop_table("raw_batches")
    op.drop_table("line_reference")
    op.drop_table("asset_reference")
