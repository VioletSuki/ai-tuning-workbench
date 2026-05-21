"""Data access, downsampling, and variable-selection utilities.

All functions in this module enforce finite-output limits so that an AI agent
never accidentally reads an unbounded telemetry file.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any

from tuner.runtime.state import RuntimeState
from tuner.utils.time_utils import parse_duration_seconds

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Downsampling
# ---------------------------------------------------------------------------


def downsample_rows(rows: list[dict], max_points: int) -> list[dict]:
    """Uniformly downsample *rows* to at most *max_points* entries.

    If ``len(rows) <= max_points`` the list is returned unchanged.
    Otherwise every ``ceil(len(rows) / max_points)``-th row is kept,
    always including the first and last row.
    """
    if max_points <= 0:
        return []
    n = len(rows)
    if n <= max_points:
        return list(rows)

    step = n / max_points
    indices = {0, n - 1}
    for i in range(1, max_points - 1):
        idx = int(round(i * step))
        if 0 < idx < n - 1:
            indices.add(idx)

    return [rows[i] for i in sorted(indices)]


# ---------------------------------------------------------------------------
# Variable selection
# ---------------------------------------------------------------------------

_MISSING_VAR_WARNING = object()  # sentinel


def select_vars(
    rows: list[dict], vars_spec: str | list[str]
) -> list[dict]:
    """Return rows containing only the requested variables.

    *vars_spec* may be ``"all"`` (return all keys) or an explicit list of
    column names.  Missing columns are silently dropped; a warning is logged
    for the first occurrence of each unknown variable.
    """
    if vars_spec == "all":
        return list(rows)

    if isinstance(vars_spec, str):
        vars_list = [v.strip() for v in vars_spec.split(",") if v.strip()]
    else:
        vars_list = list(vars_spec)

    if not vars_list:
        return []

    # Determine which requested keys actually exist
    if not rows:
        return []

    available = set(rows[0].keys())
    warned: set[str] = set()
    keep = []
    for v in vars_list:
        if v in available:
            keep.append(v)
        elif v not in warned:
            logger.warning("Variable %r not found in data — ignoring", v)
            warned.add(v)

    if not keep:
        return []

    return [{k: r[k] for k in keep if k in r} for r in rows]


# ---------------------------------------------------------------------------
# Format conversion
# ---------------------------------------------------------------------------


def rows_to_csv_text(rows: list[dict]) -> str:
    """Convert a list of dicts to CSV text (in-memory string)."""
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def rows_to_json_text(rows: list[dict]) -> str:
    """Convert a list of dicts to a JSON text (pretty-printed array)."""
    return json.dumps(rows, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Query helpers  (ring-buffer based)
# ---------------------------------------------------------------------------


def _resolve_source(
    state: RuntimeState,
    window: str | None = None,
    last: str | None = None,
) -> list[dict] | None:
    """Resolve which data source to query, returning rows or *None*.

    Priority:
      1. Explicit ``window`` name → saved window CSV.
      2. ``last`` time range → ring buffer.
      3. Neither → newest ring buffer data (default ``default_duration_s``).
    """
    if window:
        win_id = state.windows.resolve_window(window)
        if win_id is None:
            logger.warning("Window %r not found", window)
            return None
        return state.windows.get_window_rows(win_id)

    # Time range from ring buffer
    if last:
        seconds = parse_duration_seconds(last)
    else:
        seconds = state.config.project.windows.default_duration_s

    return state.ring_buffer.get_last(seconds)


def get_rows_for_query(
    state: RuntimeState,
    window: str | None = None,
    last: str | None = None,
    max_points: int | None = None,
    vars_spec: str = "all",
) -> list[dict]:
    """Return decoded telemetry rows for a query, with downsampling.

    Parameters
    ----------
    state : RuntimeState
    window : str, optional
        Saved window name (``"latest"``, ``"window_0001"``).
    last : str, optional
        Time range string (``"3s"``, ``"5m"``).
    max_points : int, optional
        Maximum points.  Falls back to manifest
        ``recording.max_cli_points`` (default 200).
    vars_spec : str
        ``"all"`` or a comma-separated / list of variable names.

    Returns
    -------
    list[dict]
        Possibly empty, always limited.
    """
    rows = _resolve_source(state, window=window, last=last)
    if rows is None:
        return []

    # Apply variable selection first (reduces memory before downsampling)
    rows = select_vars(rows, vars_spec)

    # Downsample
    limit = (
        max_points
        if max_points is not None
        else state.config.project.recording.max_cli_points
    )
    rows = downsample_rows(rows, limit)

    return rows


def get_raw_for_query(
    state: RuntimeState,
    window: str | None = None,
    last: str | None = None,
    max_frames: int | None = None,
) -> list[dict]:
    """Return raw hex frames for a query.

    Reads from the active run's ``raw/raw_frames.jsonl``.

    Parameters
    ----------
    state : RuntimeState
    window : str, optional
        Saved window name (not applicable for raw frames in current impl).
    last : str, optional
        Time range string to filter raw frames by ``host_time``.
    max_frames : int, optional
        Maximum frames.  Falls back to manifest
        ``recording.max_cli_raw_frames`` (default 100).

    Returns
    -------
    list[dict]
        Possibly empty.
    """
    limit = (
        max_frames
        if max_frames is not None
        else state.config.project.recording.max_cli_raw_frames
    )

    raw_file = _get_raw_frames_file(state)
    if raw_file is None or not raw_file.exists():
        return []

    rows: list[dict] = []
    with open(raw_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    # Filter by time range if requested
    if last and rows:
        seconds = parse_duration_seconds(last)
        # Use host_time if available (ISO string comparison fallback)
        try:
            from datetime import datetime, timezone

            if rows and "host_time" in rows[0]:
                # Use the last row's host_time as reference
                ref_str = rows[-1]["host_time"]
                ref = datetime.fromisoformat(ref_str).timestamp()
                cutoff = ref - seconds
                rows = [
                    r
                    for r in rows
                    if "host_time" in r
                    and datetime.fromisoformat(r["host_time"]).timestamp() >= cutoff
                ]
        except Exception:
            logger.warning("Could not filter raw frames by time — returning all")

    # Apply max_frames limit (take newest)
    if len(rows) > limit:
        rows = rows[-limit:]

    return rows


def _get_raw_frames_file(state: RuntimeState) -> Path | None:
    """Return the path to the active run's raw_frames.jsonl."""
    if state.recorder.run_dir is None:
        return None
    return state.recorder.run_dir / "raw" / "raw_frames.jsonl"


# ---------------------------------------------------------------------------
# Stream snapshot
# ---------------------------------------------------------------------------


def stream_snapshot(
    state: RuntimeState,
    vars_spec: str = "all",
    interval: str = "0.1s",
    duration: str = "2s",
    max_lines: int | None = None,
) -> list[dict]:
    """Collect a short snapshot of decoded rows by polling the ring buffer.

    This blocks for up to *duration* seconds.  Every *interval* the latest
    row is sampled.  Returns at most *max_lines* entries (default: unlimited
    within the duration).

    This is **not** a real WebSocket stream — it is a convenience for
    short-term observation.
    """
    import time

    interval_s = parse_duration_seconds(interval)
    duration_s = parse_duration_seconds(duration)

    # Sanity limits
    if duration_s <= 0 or interval_s <= 0:
        return []
    if duration_s > 30:
        duration_s = 30.0
    if interval_s < 0.01:
        interval_s = 0.01

    samples: list[dict] = []
    start = time.monotonic()
    last_sample_time = -1.0  # force first sample immediately

    while True:
        elapsed = time.monotonic() - start
        if elapsed >= duration_s:
            break
        if max_lines is not None and len(samples) >= max_lines:
            break

        # Sample at interval
        now = time.monotonic()
        if now - last_sample_time >= interval_s:
            row = state.ring_buffer.latest()
            if row is not None:
                samples.append(dict(row))
            last_sample_time = now

        # Sleep a short tick so we don't busy-wait at 100%
        remaining = duration_s - (time.monotonic() - start)
        if remaining <= 0:
            break
        time.sleep(min(interval_s * 0.5, 0.01))

    # Apply variable selection and limit
    if vars_spec != "all":
        samples = select_vars(samples, vars_spec)

    return samples
