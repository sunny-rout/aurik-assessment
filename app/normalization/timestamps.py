from datetime import datetime, timezone


def parse_iso8601(value) -> datetime:
    """Parses PulseForge-style ISO8601 timestamps, e.g. '2026-04-18T07:59:12Z'."""
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp is not a non-empty string")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"unparseable ISO8601 timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_epoch_ms(value) -> datetime:
    """Parses ThermexWatch-style epoch-millisecond timestamps."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"epoch ms timestamp is not numeric: {value!r}")
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)


def parse_maintaflow_datetime(value) -> datetime:
    """Parses MaintaFlow-style 'YYYY/MM/DD HH:MM:SS' timestamps (assumed UTC)."""
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp is not a non-empty string")
    try:
        dt = datetime.strptime(value, "%Y/%m/%d %H:%M:%S")
    except ValueError as exc:
        raise ValueError(f"unparseable MaintaFlow timestamp: {value!r}") from exc
    return dt.replace(tzinfo=timezone.utc)
