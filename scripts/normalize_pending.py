"""Manually runs normalization over all pending raw_events.

Temporary entry point for Phase 3 — Phase 4 wires normalize_pending_events
into the RQ worker instead of requiring a manual run.
"""

from app.db.session import SessionLocal
from app.normalization.service import normalize_pending_events


def main():
    db = SessionLocal()
    try:
        counts = normalize_pending_events(db)
        print(f"Normalized {counts['normalized']} event(s), {counts['failed']} failed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
