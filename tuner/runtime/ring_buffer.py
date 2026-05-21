"""Ring buffer — time-windowed storage of decoded data rows."""

from __future__ import annotations

from typing import Any

from tuner.utils.time_utils import monotonic_seconds


class RingBuffer:
    """Fixed-duration ring buffer of data rows.

    Each row **must** contain a ``host_monotonic`` key (set by
    :meth:`append`) used for time-based slicing.  The caller may also
    include a ``host_time`` string for ISO-8601 wall-clock tagging.

    Parameters
    ----------
    max_seconds : float
        How many seconds of data to retain (based on monotonic time).
    """

    def __init__(self, max_seconds: float) -> None:
        if max_seconds <= 0:
            raise ValueError(f"max_seconds must be > 0, got {max_seconds}")
        self._max_seconds = max_seconds
        self._buf: list[dict[str, Any]] = []

    # -- public API ---------------------------------------------------------

    def append(self, row: dict[str, Any]) -> None:
        """Append one data *row*, adding ``host_monotonic`` timestamp."""
        row["host_monotonic"] = monotonic_seconds()
        self._buf.append(row)
        self._trim()

    def get_last(self, seconds: float) -> list[dict[str, Any]]:
        """Return rows from the last *seconds* (monotonic time).

        Returns an empty list if the buffer is empty.
        """
        if seconds <= 0:
            return []
        if not self._buf:
            return []
        cutoff = self._buf[-1]["host_monotonic"] - seconds
        return [r for r in self._buf if r["host_monotonic"] >= cutoff]

    def get_all(self) -> list[dict[str, Any]]:
        """Return a copy of all buffered rows."""
        return list(self._buf)

    def latest(self) -> dict[str, Any] | None:
        """Return the most recent row, or ``None``."""
        return self._buf[-1] if self._buf else None

    def count(self) -> int:
        """Return the number of rows currently in the buffer."""
        return len(self._buf)

    def clear(self) -> None:
        """Remove all buffered rows."""
        self._buf.clear()

    # -- internals ----------------------------------------------------------

    def _trim(self) -> None:
        """Remove rows older than ``max_seconds`` from the front."""
        if not self._buf:
            return
        cutoff = self._buf[-1]["host_monotonic"] - self._max_seconds
        # Since rows are appended in order, we can drop from the front.
        while self._buf and self._buf[0]["host_monotonic"] < cutoff:
            self._buf.pop(0)
