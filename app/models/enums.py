import enum


class RawEventStatus(str, enum.Enum):
    PENDING = "pending"
    NORMALIZED = "normalized"
    FAILED = "failed"


class EventCategory(str, enum.Enum):
    VIBRATION = "vibration"
    TEMPERATURE = "temperature"
    POWER = "power"
    SENSOR_HEALTH = "sensor_health"
    INSPECTION = "inspection"
    MAINTENANCE = "maintenance"
    NOTE = "note"


class SeverityLevel(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DerivedStatus(str, enum.Enum):
    OK = "OK"
    WATCH = "WATCH"
    ATTENTION = "ATTENTION"
    CRITICAL = "CRITICAL"


class ProcessingStatus(str, enum.Enum):
    OK = "ok"
    STALE = "stale"
    PARTIAL = "partial"
    FAILED = "failed"
