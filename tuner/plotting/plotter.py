"""Matplotlib-based plotting utilities for telemetry data.

Usage::

    from tuner.plotting.plotter import plot_query
    result = plot_query(state, last="5s", x="time_ms", y=["a", "b"], save=True)
    print(result["path"])
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend by default; show() switches

import matplotlib.pyplot as plt  # noqa: E402

from tuner.runtime.state import RuntimeState
from tuner.utils.time_utils import utc_now_iso

logger = logging.getLogger(__name__)


def plot_rows(
    rows: list[dict],
    x: str,
    y: list[str],
    output_path: str | Path | None = None,
    show: bool = False,
    title: str | None = None,
) -> Path:
    """Plot one or more Y variables against an X variable and save the figure.

    Parameters
    ----------
    rows : list[dict]
        Data rows (must contain *x* and each *y* key).
    x : str
        Column name for the X axis.
    y : list[str]
        One or more column names for the Y axis.
    output_path : str | Path, optional
        Where to save the PNG.  Auto-generated if not provided.
    show : bool
        If *True*, also call ``plt.show()``.
    title : str, optional
        Plot title.

    Returns
    -------
    Path
        The saved figure path.
    """
    if not rows:
        raise ValueError("No data rows to plot")

    # Validate columns
    available = set(rows[0].keys())
    if x not in available:
        raise ValueError(f"X column {x!r} not found in data; available: {sorted(available)}")
    missing = [v for v in y if v not in available]
    if missing:
        raise ValueError(
            f"Y columns not found in data: {missing}; available: {sorted(available)}"
        )

    xs = [r[x] for r in rows]

    fig, ax = plt.subplots(figsize=(10, 5))
    for yvar in y:
        ys = [r[yvar] for r in rows]
        ax.plot(xs, ys, label=yvar, marker="", linestyle="-")

    ax.set_xlabel(x)
    ax.set_ylabel(", ".join(y))
    if title:
        ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)

    if output_path is None:
        output_path = Path(f"plot_{utc_now_iso().replace(':', '-')}.png")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    logger.info("Plot saved to %s", output_path)

    if show:
        plt.show()

    plt.close(fig)
    return output_path


def plot_query(
    state: RuntimeState,
    window: str | None = None,
    last: str | None = None,
    x: str | None = None,
    y: list[str] | None = None,
    save: bool = True,
    show: bool = False,
) -> dict[str, Any]:
    """Query data and generate a plot in one step.

    Parameters
    ----------
    state : RuntimeState
    window : str, optional
        Saved window name.
    last : str, optional
        Time range string (e.g. ``"5s"``).
    x : str, optional
        X-axis column (default: first numeric column found).
    y : list[str], optional
        Y-axis columns (default: all numeric columns except *x*).
    save : bool
        Save the PNG to disk.
    show : bool
        Open an interactive window.

    Returns
    -------
    dict
        Keys: ``path`` (saved PNG path or None), ``row_count``, ``x``, ``y``.
    """
    from tuner.runtime.data_access import get_rows_for_query, select_vars

    rows = get_rows_for_query(state, window=window, last=last, vars_spec="all")
    if not rows:
        return {"path": None, "row_count": 0, "x": x, "y": y, "error": "No data"}

    # Auto-detect columns if not specified
    available = list(rows[0].keys())
    ignore_keys = {"time_ms", "host_monotonic", "frame_index", "host_time"}

    if x is None:
        # Prefer host_monotonic as the most reliable time axis
        if "host_monotonic" in available:
            x = "host_monotonic"
        else:
            for col in available:
                if col not in ignore_keys:
                    x = col
                    break
        if x is None:
            return {"path": None, "row_count": len(rows), "error": "No usable X column"}

    if y is None:
        y = [col for col in available if col != x and col not in ignore_keys]
        if not y:
            return {"path": None, "row_count": len(rows), "error": "No usable Y column"}

    # Determine save path
    output_path: Path | None = None
    if save:
        if window:
            # Save inside the window directory
            win_id = state.windows.resolve_window(window)
            if win_id:
                win_dir = state.recorder.run_dir / "windows" / win_id
            else:
                win_dir = state.recorder.run_dir / "runtime" if state.recorder.run_dir else Path()
            output_path = win_dir / f"plot_{x}_vs_{'_'.join(y)}.png"
        elif state.recorder.run_dir:
            output_path = state.recorder.run_dir / "runtime" / f"plot_{x}_vs_{'_'.join(y)}.png"
        else:
            output_path = Path(f"plot_{x}_vs_{'_'.join(y)}.png")

    try:
        saved_path = plot_rows(
            rows=rows,
            x=x,
            y=y,
            output_path=output_path,
            show=show,
            title=f"{', '.join(y)} vs {x}",
        )
    except ValueError as exc:
        return {"path": None, "row_count": len(rows), "x": x, "y": y, "error": str(exc)}

    return {
        "path": str(saved_path),
        "row_count": len(rows),
        "x": x,
        "y": y,
    }
