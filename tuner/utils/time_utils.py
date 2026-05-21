import time
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def local_timestamp_for_dir() -> str:
    """Return local time string suitable for directory names (YYYY-MM-DD_HHMMSS)."""
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def monotonic_seconds() -> float:
    """Return monotonic timer value in seconds (not affected by system clock changes)."""
    return time.monotonic()


def parse_duration_seconds(text: str) -> float:
    """Parse a duration string like '3s', '0.1s', '2m' into seconds.

    Supports suffixes:
      - 's' for seconds
      - 'm' for minutes
    Plain numeric strings are treated as seconds.
    """
    text = text.strip()
    if text.endswith("m"):
        return float(text[:-1]) * 60.0
    if text.endswith("s"):
        return float(text[:-1])
    return float(text)
