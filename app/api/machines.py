from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.machine_views import get_machine_view, list_machine_views
from app.api.schemas import MachineView
from app.db.session import get_db

router = APIRouter(prefix="/v1/machines", tags=["machines"])


@router.get("", response_model=List[MachineView])
def list_machines(
    plant_id: Optional[str] = Query(default=None),
    line_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None, description="Filter by derived_status"),
    db: Session = Depends(get_db),
):
    views = list_machine_views(db, plant_id=plant_id, line_id=line_id)
    if status:
        views = [v for v in views if v.derived_status == status]
    return views


@router.get("/{machine_id}", response_model=MachineView)
def get_machine(machine_id: str, db: Session = Depends(get_db)):
    view = get_machine_view(db, machine_id)
    if view is None:
        raise HTTPException(status_code=404, detail="unknown machine_id")
    return view
