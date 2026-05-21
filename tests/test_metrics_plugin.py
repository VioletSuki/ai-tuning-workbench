"""Tests for the metrics module — builtins, plugin loader, and eval-window."""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from tuner.metrics.builtin import compute_builtin_metrics, mean, min_max, std
from tuner.metrics.plugin_loader import (
    compute_metric_profile,
    ensure_json_serializable,
    evaluate_window,
    load_metric_function,
)


# ---------------------------------------------------------------------------
# Built-in metrics
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time_ms": [0, 1, 2, 3, 4],
            "value": [10.0, 20.0, 30.0, 40.0, 50.0],
            "label": ["a", "b", "c", "d", "e"],
        }
    )


class TestBuiltinMinMax:
    def test_all_numeric(self, sample_df: pd.DataFrame) -> None:
        result = min_max(sample_df)
        assert "time_ms" in result
        assert result["time_ms"] == {"min": 0.0, "max": 4.0}
        assert "value" in result
        assert result["value"] == {"min": 10.0, "max": 50.0}
        assert "label" not in result  # non-numeric excluded

    def test_selected_columns(self, sample_df: pd.DataFrame) -> None:
        result = min_max(sample_df, columns=["value"])
        assert list(result.keys()) == ["value"]

    def test_empty_df(self) -> None:
        df = pd.DataFrame({"a": []})
        result = min_max(df)
        assert result == {}


class TestBuiltinMean:
    def test_basic(self, sample_df: pd.DataFrame) -> None:
        result = mean(sample_df)
        assert result["time_ms"] == pytest.approx(2.0)
        assert result["value"] == pytest.approx(30.0)

    def test_selected_columns(self, sample_df: pd.DataFrame) -> None:
        result = mean(sample_df, columns=["value"])
        assert list(result.keys()) == ["value"]


class TestBuiltinStd:
    def test_basic(self, sample_df: pd.DataFrame) -> None:
        result = std(sample_df)
        assert result["time_ms"] == pytest.approx(math.sqrt(2.5))
        assert result["value"] == pytest.approx(math.sqrt(250.0))


class TestComputeBuiltinMetrics:
    def test_multiple_metrics(self, sample_df: pd.DataFrame) -> None:
        result = compute_builtin_metrics(
            sample_df,
            [{"name": "min_max"}, {"name": "mean"}],
        )
        assert "min_max" in result
        assert "mean" in result
        assert result["mean"]["value"] == 30.0

    def test_unknown_builtin(self, sample_df: pd.DataFrame) -> None:
        with pytest.raises(ValueError, match="unknown_builtin"):
            compute_builtin_metrics(sample_df, [{"name": "unknown_builtin"}])


# ---------------------------------------------------------------------------
# JSON serialisation
# ---------------------------------------------------------------------------


class TestEnsureJsonSerializable:
    def test_basic_types(self) -> None:
        assert ensure_json_serializable({"a": 1, "b": "x"}) == {"a": 1, "b": "x"}

    def test_nan_and_inf(self) -> None:
        result = ensure_json_serializable({"nan": float("nan"), "inf": float("inf")})
        assert result["nan"] is None
        assert result["inf"] is None

    def test_bytes(self) -> None:
        result = ensure_json_serializable({"data": b"\xaa\xbb"})
        assert result["data"] == "aabb"

    def test_nested(self) -> None:
        data = {"outer": {"inner": [1, 2, 3]}}
        result = ensure_json_serializable(data)
        assert result == data

    def test_json_dumps_roundtrip(self) -> None:
        data = {"a": 1, "b": None, "c": [1, 2, 3]}
        serialised = json.dumps(ensure_json_serializable(data))
        assert json.loads(serialised) == data


# ---------------------------------------------------------------------------
# Plugin loader (using a temporary plugin file)
# ---------------------------------------------------------------------------


class TestLoadMetricFunction:
    def test_load_existing_function(self, tmp_path: Path) -> None:
        plugin = tmp_path / "my_metrics.py"
        plugin.write_text(
            "def compute_metrics(df, config=None):\n"
            '    return {"sum": float(df.sum().sum())}\n'
        )
        fn = load_metric_function(tmp_path, "my_metrics.py", "compute_metrics")
        df = pd.DataFrame({"a": [1, 2]})
        assert fn(df) == {"sum": 3.0}

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_metric_function(tmp_path, "nonexistent.py", "foo")

    def test_function_not_found(self, tmp_path: Path) -> None:
        plugin = tmp_path / "empty.py"
        plugin.write_text("# nothing\n")
        with pytest.raises(AttributeError, match="not_found"):
            load_metric_function(tmp_path, "empty.py", "not_found")


# ---------------------------------------------------------------------------
# compute_metric_profile (needs a full ConfigBundle — use a minimal mock)
# ---------------------------------------------------------------------------


def _make_config_bundle(
    tmp_path: Path,
    profiles: dict | None = None,
) -> "ConfigBundle":
    from tuner.config.schema import (
        BackendConfig,
        ConfigBundle,
        MetricsManifest,
        ProjectManifest,
        ProtocolManifest,
    )

    if profiles is None:
        profiles = {
            "default": {
                "builtin": [{"name": "min_max"}, {"name": "mean"}],
            }
        }

    return ConfigBundle(
        project_dir=tmp_path,
        project=ProjectManifest(
            project_name="test",
            description="test",
            backend=BackendConfig(type="mock"),
        ),
        protocol=ProtocolManifest(
            tx_frame={
                "header": "AA",
                "tail": "FF",
                "message_id": "10",
                "payload": [{"name": "x", "type": "float32"}],
            },
            rx_frame={
                "header": "AB",
                "tail": "FF",
                "message_id": "20",
                "payload": [{"name": "x", "type": "float32"}],
            },
        ),
        metrics=MetricsManifest(metric_profiles=profiles),
    )


class TestComputeMetricProfile:
    def test_builtin_profile(self, tmp_path: Path) -> None:
        config = _make_config_bundle(tmp_path)
        rows = [{"value": 1.0}, {"value": 2.0}, {"value": 3.0}]
        result = compute_metric_profile(config, "default", rows)
        assert "min_max" in result
        assert result["min_max"]["value"]["min"] == 1.0
        assert result["min_max"]["value"]["max"] == 3.0
        assert "mean" in result

    def test_unknown_profile(self, tmp_path: Path) -> None:
        config = _make_config_bundle(tmp_path)
        with pytest.raises(ValueError, match="nope"):
            compute_metric_profile(config, "nope", [])

    def test_plugin_profile(self, tmp_path: Path) -> None:
        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir()
        plugin = metrics_dir / "custom.py"
        plugin.write_text(
            "def compute_metrics(df, config=None):\n"
            '    return {"custom_sum": float(df["x"].sum())}\n'
        )
        profiles = {
            "custom": {
                "plugin": "metrics/custom.py",
                "function": "compute_metrics",
            }
        }
        config = _make_config_bundle(tmp_path, profiles)
        rows = [{"x": 10.0}, {"x": 20.0}]
        result = compute_metric_profile(config, "custom", rows)
        assert result["custom_sum"] == 30.0


# ---------------------------------------------------------------------------
# evaluate_window
# ---------------------------------------------------------------------------


class TestEvaluateWindow:
    def test_requires_window_or_last(self, tmp_path: Path) -> None:
        config = _make_config_bundle(tmp_path)
        state = _make_runtime_state(config)
        with pytest.raises(ValueError, match="Either"):
            evaluate_window(config, state)

    def test_last_seconds(self, tmp_path: Path) -> None:
        config = _make_config_bundle(tmp_path)
        state = _make_runtime_state(config)
        # Push some data into the ring buffer
        import time

        for i in range(5):
            row = {"value": float(i)}
            state.append_decoded(row)
            time.sleep(0.005)

        result = evaluate_window(config, state, last="10s")
        assert result["ok"] is True
        assert result["row_count"] == 5
        assert "min_max" in result["metrics"]
        assert result["metrics"]["min_max"]["value"]["min"] == 0.0
        assert result["metrics"]["min_max"]["value"]["max"] == 4.0


def _make_runtime_state(config: "ConfigBundle") -> "RuntimeState":
    from tuner.runtime.state import RuntimeState

    return RuntimeState(config)
