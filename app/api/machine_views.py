from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import MachineView
from app.models.machine_state import MachineState
from app.models.reference import AssetReference

DEFAULT_STATUS = "OK"
DEFAULT_PROCESSING_STATUS = "failed"  # no data processed yet for this machine


def _to_view(asset: AssetReference, state: Optional[MachineState]) -> MachineView:
    if state is None:
        return MachineView(
            machine_id=asset.machine_id,
            plant_id=asset.plant_id,
            line_id=asset.line_id,
            criticality=asset.criticality,
            derived_status=DEFAULT_STATUS,
            attention_level=1,
            reason_codes=[],
            latest_relevant_event_time=None,
            processing_status=DEFAULT_PROCESSING_STATUS,
            source_event_refs=[],
            last_processed_at=None,
        )
    return MachineView(
        machine_id=state.machine_id,
        plant_id=state.plant_id,
        line_id=state.line_id,
        criticality=asset.criticality,
        derived_status=state.derived_status,
        attention_level=state.attention_level,
        reason_codes=state.reason_codes or [],
        latest_relevant_event_time=state.latest_relevant_event_time,
        processing_status=state.processing_status,
        source_event_refs=state.source_event_refs or [],
        last_processed_at=state.last_processed_at,
    )


def get_machine_view(db: Session, machine_id: str) -> Optional[MachineView]:
    asset = db.get(AssetReference, machine_id)
    if asset is None:
        return None
    state = db.get(MachineState, machine_id)
    return _to_view(asset, state)


def list_machine_views(
    db: Session, plant_id: Optional[str] = None, line_id: Optional[str] = None
) -> List[MachineView]:
    query = select(AssetReference)
    if plant_id:
        query = query.where(AssetReference.plant_id == plant_id)
    if line_id:
        query = query.where(AssetReference.line_id == line_id)
    assets = db.execute(query).scalars().all()

    states = {
        state.machine_id: state
        for state in db.execute(select(MachineState)).scalars().all()
    }

    return [_to_view(asset, states.get(asset.machine_id)) for asset in assets]
