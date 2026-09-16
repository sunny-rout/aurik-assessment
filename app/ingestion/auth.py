from fastapi import Header, HTTPException

from app.config import settings

_VENDOR_KEYS = {
    "pulseforge": lambda: settings.pulseforge_api_key,
    "thermexwatch": lambda: settings.thermexwatch_api_key,
    "maintaflow": lambda: settings.maintaflow_api_key,
}


def require_vendor_key(vendor: str):
    expected_key_fn = _VENDOR_KEYS[vendor]

    def _verify(x_vendor_key: str = Header(...)) -> None:
        if x_vendor_key != expected_key_fn():
            raise HTTPException(status_code=401, detail="invalid vendor key")

    return _verify
