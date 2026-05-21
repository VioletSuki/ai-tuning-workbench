"""Interactive real-time plotting for telemetry data.

This module sets its own matplotlib interactive backend and is deliberately
separate from plotter.py (which uses the non-interactive Agg backend).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Must set backend BEFORE importing pyplot
try:
    import matplotlib

    matplotlib.use("TkAgg")
except ImportError:
    raise ImportError(
        "TkAgg backend is required for live plotting. "
        "Install it with: pip install python-tk"
    )

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.animation import FuncAnimation  # noqa: E402


def plot_live(
    fetch_data: Callable[[], list[dict[str, Any]]],
    x: str = "host_monotonic",
    y: list[str] | None = None,
    window_seconds: float = 5.0,
    refresh_ms: int = 200,
    title: str | None = None,
    auto_scale_y: bool = True,
) -> None:
    """Open an interactive matplotlib window showing real-time telemetry data.

    Parameters
    ----------
    fetch_data : Callable[[], list[dict]]
        A zero-argument callable that returns telemetry rows (list of dicts).
        Typically wraps ``client.get_data(last="5s")["rows"]``.
    x : str
        Column name for the X axis (default: ``host_monotonic``).
    y : list[str]
        One or more column names for the Y axis.
    window_seconds : float
        How many seconds of historical data to display (default 5.0).
    refresh_ms : int
        Animation interval in milliseconds (default 200).
    title : str, optional
        Plot window title.
    auto_scale_y : bool
        If *True* (default), the Y-axis range adjusts dynamically on every
        frame.  Set to *False* for expand-only mode: the Y range grows when
        data exceeds the current limits, but never shrinks.

    Notes
    -----
    Blocks until the user closes the matplotlib window.  Ctrl+C is caught
    and exits cleanly.  If the daemon becomes unreachable the plot freezes
    on the last successful data instead of crashing.
    """
    if not y:
        raise ValueError("At least one Y variable must be specified")

    # Initial data fetch — may be empty if no data yet
    try:
        rows = fetch_data()
    except Exception as exc:
        logger.warning("Initial data fetch failed: %s", exc)
        rows = []

    fig, ax = plt.subplots(figsize=(10, 5))
    lines: dict[str, Any] = {}
    for yvar in y:
        (line,) = ax.plot([], [], label=yvar, marker="", linestyle="-")
        lines[yvar] = line

    ax.set_xlabel(x)
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.3)
    if title:
        ax.set_title(title)

    # Pre-seed with initial data if available
    _y_bounds: list[float | None] = [None, None]
    if rows:
        xs = [r[x] for r in rows]
        for yvar in y:
            ys = [r.get(yvar) for r in rows]
            valid = [(xv, yv) for xv, yv in zip(xs, ys) if yv is not None]
            if valid:
                lines[yvar].set_data([p[0] for p in valid], [p[1] for p in valid])
        ax.relim()
        ax.autoscale_view()
        if not auto_scale_y:
            _y_bounds = list(ax.get_ylim())

    def _update(_frame_num: int) -> list[Any]:
        try:
            current_rows = fetch_data()
        except Exception as exc:
            logger.debug("Live plot fetch failed: %s", exc)
            return list(lines.values())

        if not current_rows:
            return list(lines.values())

        xs = [r[x] for r in current_rows]

        for yvar in lines:
            ys = [r.get(yvar) for r in current_rows]
            valid = [(xv, yv) for xv, yv in zip(xs, ys) if yv is not None]
            if valid:
                lines[yvar].set_data([p[0] for p in valid], [p[1] for p in valid])

        ax.relim()
        if auto_scale_y:
            ax.autoscale_view()
        else:
            ax.autoscale_view(scaley=False)
            # Expand-only: grow Y limits when data exceeds range, never shrink
            for yvar in lines:
                ys = [r.get(yvar) for r in current_rows]
                for yv in ys:
                    if yv is not None:
                        if _y_bounds[0] is None or yv < _y_bounds[0]:
                            _y_bounds[0] = yv
                        if _y_bounds[1] is None or yv > _y_bounds[1]:
                            _y_bounds[1] = yv
            if _y_bounds[0] is not None and _y_bounds[1] is not None:
                y_range = _y_bounds[1] - _y_bounds[0]
                if y_range > 0:
                    pad = y_range * 0.05
                    ax.set_ylim(_y_bounds[0] - pad, _y_bounds[1] + pad)

        # Rolling window: show last window_seconds of data
        if xs:
            x_min = xs[0]
            x_max = xs[-1]
            x_range = x_max - x_min
            if x_range > 0:
                padding = x_range * 0.05
                ax.set_xlim(x_min - padding, x_max + padding)

        return list(lines.values())

    ani = FuncAnimation(
        fig, _update, interval=refresh_ms, blit=True, cache_frame_data=False
    )

    try:
        plt.show()
    except KeyboardInterrupt:
        logger.info("Live plot closed via Ctrl+C")
    finally:
        plt.close(fig)
