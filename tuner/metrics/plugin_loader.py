"""Dynamic plugin loader for user-defined metric functions and eval-window orchestration.

Plugin contracts
----------------
A metrics plugin is any Python file that exposes a function with signature::

    def compute_metrics(df: pandas.DataFrame, config: dict | None = None) -> dict:
        ...

The *config* dict is the full ``MetricProfile`` dict (from the manifest) so the
plugin can read its own ``inputs`` mapping or any extra fields.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from tuner.config.schema import ConfigBundle
from tuner.runtime.state import RuntimeState


# ---------------------------------------------------------------------------
# JSON-serialisation helpers
# ---------------------------------------------------------------------------

_BASIC_TYPES = (type(None), bool, int, float, str)


def _numpy_available() -> bool:
    try:
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


_HAS_NUMPY = _numpy_available()
if _HAS_NUMPY:
    import numpy as np


def _convert_value(val: Any) -> Any:
    """Recursively convert *val* to a JSON-safe type."""
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    if isinstance(val, _BASIC_TYPES):
        return val
    if isinstance(val, (list, tuple)):
        return [_convert_value(v) for v in val]
    if isinstance(val, dict):
        return {k: _convert_value(v) for k, v in val.items()}
    if _HAS_NUMPY and isinstance(val, np.generic):
        return val.item()
    if isinstance(val, bytes):
        return val.hex()
    return str(val)


def ensure_json_serializable(data: dict) -> dict:
    """Walk *data* and convert non-JSON-safe values (numpy, NaN, bytes…)."""
    return _convert_value(data)


# ---------------------------------------------------------------------------
# Plugin loader
# ---------------------------------------------------------------------------


def load_metric_function(
    project_dir: str | Path,
    plugin_path: str,
    function_name: str,
) -> Any:
    """Dynamically import a metric function from a Python file.

    Parameters
    ----------
    project_dir : str | Path
        Absolute path to the project root (used to resolve relative paths).
    plugin_path : str
        Path to the plugin file, relative to *project_dir*.
    function_name : str
        Name of the callable to extract from the module.

    Returns
    -------
    callable
        The imported function.

    Raises
    ------
    FileNotFoundError
        If the plugin file does not exist.
    AttributeError
        If the function is not found in the module.
    """
    project_dir = Path(project_dir)
    abs_path = (project_dir / plugin_path).resolve()

    if not abs_path.exists():
        raise FileNotFoundError(f"Metric plugin not found: {abs_path}")

    spec = importlib.util.spec_from_file_location("_metric_plugin", abs_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec from {abs_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, function_name):
        raise AttributeError(
            f"Function {function_name!r} not found in {abs_path}; "
            f"available: {[n for n in dir(module) if not n.startswith('_')]}"
        )

    return getattr(module, function_name)


# ---------------------------------------------------------------------------
# Profile computation
# ---------------------------------------------------------------------------


def compute_metric_profile(
    config_bundle: ConfigBundle,
    profile_name: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute metrics for *profile_name* as declared in the metrics manifest.

    The profile can be either:
    - A ``builtin`` profile — runs the listed built-in metrics.
    - A ``plugin`` profile — dynamically loads the plugin function and calls it.

    Parameters
    ----------
    config_bundle : ConfigBundle
        Loaded project configuration (must include ``metrics`` manifest).
    profile_name : str
        Name of the profile (key in ``metrics_manifest.metric_profiles``).
    rows : list[dict]
        Data rows to evaluate (each row is a decoded telemetry dict).

    Returns
    -------
    dict
        JSON-serialisable metrics result.
    """
    profiles = config_bundle.metrics.metric_profiles
    if profile_name not in profiles:
        raise ValueError(
            f"Unknown metric profile {profile_name!r}; "
            f"available: {list(profiles)}"
        )

    profile = profiles[profile_name]
    df = pd.DataFrame(rows)

    # -- builtin profile -----------------------------------------------------
    if profile.builtin is not None:
        from tuner.metrics.builtin import compute_builtin_metrics

        result = compute_builtin_metrics(df, profile.builtin)
        return ensure_json_serializable(result)

    # -- plugin profile ------------------------------------------------------
    if profile.plugin is not None and profile.function is not None:
        fn = load_metric_function(
            config_bundle.project_dir,
            profile.plugin,
            profile.function,
        )
        # Pass the full profile dict as config so the plugin can use inputs etc.
        config_dict = profile.model_dump()
        config_dict["profile_name"] = profile_name

        plugin_result = fn(df, config=config_dict)
        return ensure_json_serializable(plugin_result)

    raise ValueError(
        f"Profile {profile_name!r} has neither 'builtin' nor 'plugin' configuration"
    )


# ---------------------------------------------------------------------------
# eval-window orchestration
# ---------------------------------------------------------------------------


def evaluate_window(
    config_bundle: ConfigBundle,
    runtime_state: RuntimeState,
    window: str | None = None,
    last: str | float | None = None,
    metrics_profile: str = "default",
) -> dict[str, Any]:
    """Evaluate metrics on a window of data and persist results.

    Data source priority:
        1. ``window`` — a saved or ``"latest"`` window (via WindowManager).
        2. ``last`` — time-based slice from the ring buffer (e.g. ``"3s"``).

    The result is saved to:
    - ``<run_dir>/windows/<window_id>/metrics_<profile>.json`` (if a saved window)
    - ``<run_dir>/runtime/latest_metrics.json``

    ``runtime_state.latest_metrics`` is also updated.

    Parameters
    ----------
    config_bundle : ConfigBundle
        Loaded project configuration.
    runtime_state : RuntimeState
        Active runtime state with ring buffer, windows, and recorder.
    window : str, optional
        Window identifier — ``"latest"`` or ``"window_XXXX"``.
    last : str or float, optional
        Time-duration string like ``"3s"`` or a float in seconds.
    metrics_profile : str
        Name of the metric profile to use (default ``"default"``).

    Returns
    -------
    dict
        ``{"ok": True, "metrics": …, "profile": …, "source": …}``
    """
    rows: list[dict] = []
    source_desc: str = ""
    window_id: str | None = None

    # Priority 1: explicit window
    if window is not None:
        resolved = runtime_state.windows.resolve_window(window)
        if resolved is None:
            raise ValueError(
                f"Window {window!r} not found; available: {runtime_state.windows.list_windows()}"
            )
        window_id = resolved
        rows = runtime_state.windows.get_window_rows(window_id)
        source_desc = f"saved_window/{window_id}"
    # Priority 2: last-N-seconds from ring buffer
    elif last is not None:
        seconds = _parse_seconds(last)
        rows = runtime_state.windows.get_last_window(seconds)
        source_desc = f"ring_buffer/last_{seconds}s"
    else:
        raise ValueError("Either 'window' or 'last' must be provided")

    if not rows:
        result: dict[str, Any] = {
            "ok": True,
            "metrics": {},
            "profile": metrics_profile,
            "source": source_desc,
            "row_count": 0,
            "note": "no data rows in window",
        }
    else:
        metrics_data = compute_metric_profile(config_bundle, metrics_profile, rows)
        result = {
            "ok": True,
            "metrics": metrics_data,
            "profile": metrics_profile,
            "source": source_desc,
            "row_count": len(rows),
        }

    # Persist
    _persist_metrics(runtime_state, result, window_id, metrics_profile)

    runtime_state.latest_metrics = result
    return result


def _parse_seconds(value: str | float) -> float:
    """Parse a duration string like ``"3s"`` or a plain number into seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s.endswith("s"):
        s = s[:-1]
    return float(s)


def _persist_metrics(
    state: RuntimeState,
    result: dict[str, Any],
    window_id: str | None,
    profile: str,
) -> None:
    """Write metrics result to disk."""
    run_dir = state.recorder.run_dir
    if run_dir is None:
        return  # no active run — nothing to persist

    # Per-window file
    if window_id is not None:
        win_dir = run_dir / "windows" / window_id
        win_dir.mkdir(parents=True, exist_ok=True)
        metrics_file = win_dir / f"metrics_{profile}.json"
        metrics_file.write_text(
            json.dumps(ensure_json_serializable(result), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # Runtime latest
    runtime_dir = run_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "latest_metrics.json").write_text(
        json.dumps(ensure_json_serializable(result), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
