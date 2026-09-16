from sqlalchemy import Column, Date, Float, String

from app.db.session import Base


class AssetReference(Base):
    """Machine reference data, seeded from asset_reference.csv."""

    __tablename__ = "asset_reference"

    machine_id = Column(String, primary_key=True)
    plant_id = Column(String, nullable=False, index=True)
    line_id = Column(String, nullable=False, index=True)
    machine_type = Column(String, nullable=False)
    criticality = Column(String, nullable=False)
    installed_date = Column(Date, nullable=True)
    rated_max_temp_c = Column(Float, nullable=True)
    rated_max_vibration_mm_s = Column(Float, nullable=True)
    baseline_power_kw = Column(Float, nullable=True)
    asset_status = Column(String, nullable=False)


class LineReference(Base):
    """Line/plant reference data, seeded from line_reference.csv."""

    __tablename__ = "line_reference"

    line_id = Column(String, primary_key=True)
    plant_id = Column(String, nullable=False, index=True)
    line_name = Column(String, nullable=False)
    operating_window = Column(String, nullable=False)
