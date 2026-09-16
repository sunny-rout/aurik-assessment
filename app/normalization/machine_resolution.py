from typing import Dict, Tuple

from app.models.reference import AssetReference
from app.normalization.errors import NormalizationError


def resolve_machine(raw_machine_id, asset_lookup: Dict[str, AssetReference]) -> Tuple[str, str, str]:
    """Resolves a vendor-supplied machine identifier against reference data.

    Reference data (asset_reference) is treated as the source of truth for
    plant_id/line_id — vendor-supplied plant/line fields are not trusted,
    since they're inconsistent across vendors (e.g. ThermexWatch's
    productionLine is just a bare letter) and reference data is curated.
    """
    if raw_machine_id is None or not str(raw_machine_id).strip():
        raise NormalizationError("MISSING_MACHINE_ID")

    machine_id = str(raw_machine_id).strip()
    asset = asset_lookup.get(machine_id)
    if asset is None:
        raise NormalizationError("UNKNOWN_ASSET")

    return asset.machine_id, asset.plant_id, asset.line_id
