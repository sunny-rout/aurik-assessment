"""Loads asset_reference.csv and line_reference.csv into the reference tables.

Idempotent: re-running upserts rows by primary key instead of duplicating them,
so it is safe to run on every container startup.
"""

import csv
import os
from datetime import datetime

from app.config import settings
from app.db.session import Base, SessionLocal, engine
from app.models.reference import AssetReference, LineReference


def _parse_date(value: str):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_float(value: str):
    if value in (None, ""):
        return None
    return float(value)


def load_asset_reference(db, path: str) -> int:
    count = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            record = AssetReference(
                machine_id=row["machine_id"],
                plant_id=row["plant_id"],
                line_id=row["line_id"],
                machine_type=row["machine_type"],
                criticality=row["criticality"],
                installed_date=_parse_date(row["installed_date"]),
                rated_max_temp_c=_parse_float(row["rated_max_temp_c"]),
                rated_max_vibration_mm_s=_parse_float(row["rated_max_vibration_mm_s"]),
                baseline_power_kw=_parse_float(row["baseline_power_kw"]),
                asset_status=row["asset_status"],
            )
            db.merge(record)
            count += 1
    return count


def load_line_reference(db, path: str) -> int:
    count = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            record = LineReference(
                line_id=row["line_id"],
                plant_id=row["plant_id"],
                line_name=row["line_name"],
                operating_window=row["operating_window"],
            )
            db.merge(record)
            count += 1
    return count


def main():
    Base.metadata.create_all(bind=engine, tables=[
        AssetReference.__table__,
        LineReference.__table__,
    ])

    asset_csv = os.path.join(settings.reference_data_dir, "asset_reference.csv")
    line_csv = os.path.join(settings.reference_data_dir, "line_reference.csv")

    db = SessionLocal()
    try:
        asset_count = load_asset_reference(db, asset_csv)
        line_count = load_line_reference(db, line_csv)
        db.commit()
        print(f"Seeded {asset_count} asset_reference rows, {line_count} line_reference rows.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
