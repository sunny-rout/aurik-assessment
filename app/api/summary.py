from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.machine_views import list_machine_views
from app.api.schemas import LineSummary, MachineView, PlantSummary
from app.db.session import get_db
from app.models.reference import LineReference

router = APIRouter(prefix="/v1", tags=["summary"])


def _summarize(views: List[MachineView]) -> dict:
    status_counts = {"OK": 0, "WATCH": 0, "ATTENTION": 0, "CRITICAL": 0}
    critical_machines = []
    stale_count = 0
    failed_count = 0

    for view in views:
        status_counts[view.derived_status] = status_counts.get(view.derived_status, 0) + 1
        if view.derived_status == "CRITICAL":
            critical_machines.append(view.machine_id)
        if view.processing_status == "stale":
            stale_count += 1
        elif view.processing_status == "failed":
            failed_count += 1

    return {
        "status_counts": status_counts,
        "critical_machines": critical_machines,
        "stale_count": stale_count,
        "failed_count": failed_count,
    }


@router.get("/plants/{plant_id}/summary", response_model=PlantSummary)
def get_plant_summary(plant_id: str, db: Session = Depends(get_db)):
    views = list_machine_views(db, plant_id=plant_id)
    if not views:
        raise HTTPException(status_code=404, detail="unknown plant_id or plant has no machines")

    stats = _summarize(views)

    lines = db.execute(select(LineReference).where(LineReference.plant_id == plant_id)).scalars().all()
    line_summaries = []
    for line in lines:
        line_views = [v for v in views if v.line_id == line.line_id]
        line_stats = _summarize(line_views)
        line_summaries.append(
            LineSummary(
                line_id=line.line_id,
                line_name=line.line_name,
                plant_id=plant_id,
                total_machines=len(line_views),
                **line_stats,
            )
        )
    # most machines requiring attention (ATTENTION + CRITICAL) first
    line_summaries.sort(
        key=lambda ls: ls.status_counts["ATTENTION"] + ls.status_counts["CRITICAL"], reverse=True
    )

    return PlantSummary(
        plant_id=plant_id,
        total_machines=len(views),
        lines=line_summaries,
        **stats,
    )


@router.get("/lines/{line_id}/summary", response_model=LineSummary)
def get_line_summary(line_id: str, db: Session = Depends(get_db)):
    line = db.get(LineReference, line_id)
    if line is None:
        raise HTTPException(status_code=404, detail="unknown line_id")

    views = list_machine_views(db, line_id=line_id)
    stats = _summarize(views)

    return LineSummary(
        line_id=line.line_id,
        line_name=line.line_name,
        plant_id=line.plant_id,
        total_machines=len(views),
        **stats,
    )
