class NormalizationError(Exception):
    """Raised when a raw record cannot be normalized.

    `reason` is a short machine-readable code (e.g. MISSING_MACHINE_ID,
    UNKNOWN_ASSET, INVALID_FIELD:event_time) stored on the raw_event /
    dead_letter_events row so failures stay explainable.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)
