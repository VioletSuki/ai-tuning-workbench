"""WindowManager — explicit and time-based data window slicing."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from tuner.runtime.ring_buffer import RingBuffer
from tuner.runtime.recorder import RunRecorder
from tuner.utils.time_utils import monotonic_seconds, utc_now_iso


class WindowManager:
    """Manages explicit (start/end) and ad-hoc (last-N-seconds) windows.

    Parameters
    ----------
    ring_buffer : RingBuffer
        Shared ring buffer to slice data from.
    recorder : RunRecorder
        Recorder for persisting completed windows.
    """

    def __init__(
        self,
        ring_buffer: RingBuffer,
        recorder: RunRecorder,
    ) -> None:
        self._ring = ring_buffer
        self._recorder = recorder
        self._start_marker: float | None = None  # monotonic time at mark_start
        self._start_tag: str | None = None
        self._window_counter: int = 0
        self._latest_window_id: str | None = None
        self._saved_windows: dict[str, dict[str, Any]] = {}  # id -> meta

    # -- explicit start / end ----------------------------------------------

    def mark_start(self, tag: str | None = None) -> dict[str, Any]:
        """Mark the beginning of an explicit data window.

        Stores a monotonic timestamp and a tag.  Does **not** send any
        control command to the device.

        Returns a dict with ``tag``, ``start_time`` (ISO), and ``start_monotonic``.
        """
        self._start_marker = monotonic_seconds()
        self._start_tag = tag
        result = {
            "tag": tag,
            "start_time": utc_now_iso(),
            "start_monotonic": self._start_marker,
        }
        return result

    def mark_end(self) -> dict[str, Any]:
        """Mark the end of the explicit window and persist it.

        Slices the ring buffer from the ``mark_start`` marker to now,
        then saves the slice via ``RunRecorder.write_window``.

        Returns a dict with window metadata, or raises ``RuntimeError`` if
        ``mark_start`` was not called first.
        """
        if self._start_marker is None:
            raise RuntimeError("mark_start() must be called before mark_end()")

        end_monotonic = monotonic_seconds()
        end_time = utc_now_iso()

        # Slice rows from start marker to end
        rows = [
            r
            for r in self._ring.get_all()
            if r.get("host_monotonic", 0) >= self._start_marker
        ]

        # Increment counter and build window_id
        self._window_counter += 1
        window_id = f"window_{self._window_counter:04d}"
        self._latest_window_id = window_id

        meta = {
            "window_id": window_id,
            "tag": self._start_tag,
            "start_time": utc_now_iso(),
            "start_monotonic": self._start_marker,
            "end_time": end_time,
            "end_monotonic": end_monotonic,
            "row_count": len(rows),
        }

        # Write via recorder
        self._recorder.write_window(window_id, rows, meta)
        self._saved_windows[window_id] = dict(meta)

        # Reset marker
        self._start_marker = None
        self._start_tag = None

        return meta

    # -- ad-hoc window ------------------------------------------------------

    def get_last_window(self, seconds: float) -> list[dict[str, Any]]:
        """Return rows from the last *seconds* without persisting.

        This is a stateless query on the ring buffer.
        """
        return self._ring.get_last(seconds)

    # -- saved window access ------------------------------------------------

    def get_window_rows(self, window_id: str) -> list[dict[str, Any]]:
        """Read back the telemetry CSV for a previously saved window.

        Returns a list of dicts (empty list if the file is missing or empty).
        """
        if self._recorder.run_dir is None:
            return []
        win_dir = self._recorder.run_dir / "windows" / window_id
        csv_path = win_dir / "telemetry.csv"
        if not csv_path.exists():
            return []
        with open(csv_path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def list_windows(self) -> list[dict[str, Any]]:
        """Return metadata for all saved windows, in creation order."""
        return [self._saved_windows[k] for k in sorted(self._saved_windows.keys())]

    @property
    def latest_window_id(self) -> str | None:
        """The window id of the most recently completed window, or ``None``."""
        return self._latest_window_id

    # -- resolution helper --------------------------------------------------

    def resolve_window(self, window_spec: str) -> str | None:
        """Resolve a user-supplied window string to a concrete window id.

        - ``"latest"`` -> ``latest_window_id``
        - ``"window_XXXX"`` -> returned as-is if it exists

        Returns ``None`` if not found.
        """
        if window_spec == "latest":
            return self._latest_window_id
        if window_spec in self._saved_windows:
            return window_spec
        return None
