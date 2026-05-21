"""Tests for manifest schema and loader."""

import tempfile
from pathlib import Path

import pytest
import yaml

from tuner.config.loader import load_project, get_tx_field_names, get_rx_field_names, resolve_project_file
from tuner.config.schema import (
    ConfigBundle,
    FieldSpec,
    FrameSpec,
    MetricsManifest,
    ProjectManifest,
    ProtocolManifest,
)

# ---------------------------------------------------------------------------
# Sample manifest data
# ---------------------------------------------------------------------------

SAMPLE_PROJECT = {
    "project_name": "test_project",
    "description": "A test project",
    "backend": {
        "type": "mock",
    },
}

SAMPLE_PROTOCOL = {
    "mode": "fixed_binary",
    "display": "hex",
    "tx_frame": {
        "header": "AA",
        "tail": "FF",
        "message_id": "10",
        "checksum": "sum_u8",
        "endian": "big",
        "payload": [
            {"name": "kp", "type": "float32", "wire_scale": 1.0, "min": 0.0, "max": 10.0},
        ],
    },
    "rx_frame": {
        "header": "AB",
        "tail": "FF",
        "message_id": "20",
        "checksum": "sum_u8",
        "endian": "big",
        "payload": [
            {"name": "measured", "type": "float32"},
        ],
    },
}

SAMPLE_METRICS = {
    "metric_profiles": {
        "default": {
            "plugin": "metrics/custom_metrics.py",
            "function": "compute_metrics",
            "inputs": {"value": "measured"},
        },
        "raw_preview": {
            "builtin": [{"name": "min_max"}, {"name": "mean"}],
        },
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_project():
    """Create a temporary project directory with all three manifests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manifests_dir = Path(tmpdir) / "manifests"
        manifests_dir.mkdir(parents=True)
        for name, data in [
            ("project_manifest.yaml", SAMPLE_PROJECT),
            ("protocol_manifest.yaml", SAMPLE_PROTOCOL),
            ("metrics_manifest.yaml", SAMPLE_METRICS),
        ]:
            (manifests_dir / name).write_text(yaml.dump(data))
        yield Path(tmpdir)


# ---------------------------------------------------------------------------
# Loader tests
# ---------------------------------------------------------------------------


class TestLoadProject:
    def test_success(self, temp_project):
        bundle = load_project(temp_project)
        assert isinstance(bundle, ConfigBundle)
        assert bundle.project_dir == temp_project
        assert bundle.project.project_name == "test_project"
        assert bundle.project.backend.type == "mock"
        assert bundle.protocol.mode == "fixed_binary"
        assert bundle.protocol.tx_frame.payload[0].name == "kp"
        assert bundle.metrics.metric_profiles["default"].plugin == "metrics/custom_metrics.py"

    def test_missing_project_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FileNotFoundError, match="project_manifest"):
                load_project(tmpdir)

    def test_missing_protocol_file(self, temp_project):
        (temp_project / "manifests" / "protocol_manifest.yaml").unlink()
        with pytest.raises(FileNotFoundError, match="protocol_manifest"):
            load_project(temp_project)

    def test_missing_metrics_file(self, temp_project):
        (temp_project / "manifests" / "metrics_manifest.yaml").unlink()
        with pytest.raises(FileNotFoundError, match="metrics_manifest"):
            load_project(temp_project)


# ---------------------------------------------------------------------------
# Schema unit tests
# ---------------------------------------------------------------------------


class TestFieldSpec:
    def test_defaults(self):
        field = FieldSpec(name="test", type="uint8")
        assert field.wire_scale == 1.0
        assert field.min is None
        assert field.max is None

    def test_invalid_type(self):
        with pytest.raises(ValueError, match="Unsupported field type"):
            FieldSpec(name="bad", type="int64")

    def test_all_valid_types(self):
        for t in ("uint8", "int8", "uint16", "int16", "uint32", "int32", "float32"):
            field = FieldSpec(name="x", type=t)
            assert field.type == t


class TestFrameSpec:
    def test_empty_payload(self):
        with pytest.raises(ValueError, match="payload must not be empty"):
            FrameSpec(header="AA", tail="FF", message_id="10", payload=[])


class TestBackendConfig:
    def test_invalid_type(self):
        with pytest.raises(ValueError, match="Input should be 'serial', 'mock' or 'sim'"):
            ProjectManifest(
                project_name="x",
                description="x",
                backend={"type": "invalid"},
            )


class TestProtocolMode:
    def test_invalid_mode(self):
        with pytest.raises(ValueError, match="Input should be 'fixed_binary'"):
            ProtocolManifest(
                mode="variable",
                tx_frame={
                    "header": "AA", "tail": "FF", "message_id": "10",
                    "payload": [{"name": "x", "type": "uint8"}],
                },
                rx_frame={
                    "header": "AB", "tail": "FF", "message_id": "20",
                    "payload": [{"name": "y", "type": "uint8"}],
                },
            )


class TestProtocolManifestDefaults:
    def test_defaults_applied(self):
        proto = ProtocolManifest(
            tx_frame={
                "header": "AA", "tail": "FF", "message_id": "10",
                "payload": [{"name": "x", "type": "uint8"}],
            },
            rx_frame={
                "header": "AB", "tail": "FF", "message_id": "20",
                "payload": [{"name": "y", "type": "uint8"}],
            },
        )
        assert proto.mode == "fixed_binary"
        assert proto.display == "hex"
        assert proto.tx_frame.checksum == "sum_u8"
        assert proto.tx_frame.endian == "big"


class TestMetricsManifest:
    def test_with_builtin(self):
        metrics = MetricsManifest(metric_profiles={
            "raw_preview": {"builtin": [{"name": "min_max"}]},
        })
        profile = metrics.metric_profiles["raw_preview"]
        assert profile.builtin == [{"name": "min_max"}]
        assert profile.plugin is None

    def test_with_plugin(self):
        metrics = MetricsManifest(metric_profiles={
            "default": {
                "plugin": "metrics/custom.py",
                "function": "compute",
                "inputs": {"val": "rx_col"},
            },
        })
        profile = metrics.metric_profiles["default"]
        assert profile.plugin == "metrics/custom.py"
        assert profile.inputs == {"val": "rx_col"}


class TestGetFieldNames:
    def test_tx_and_rx(self):
        proto = ProtocolManifest(
            tx_frame={
                "header": "AA", "tail": "FF", "message_id": "10",
                "payload": [
                    {"name": "kp", "type": "float32"},
                    {"name": "ki", "type": "float32"},
                ],
            },
            rx_frame={
                "header": "AB", "tail": "FF", "message_id": "20",
                "payload": [{"name": "measured", "type": "float32"}],
            },
        )
        assert get_tx_field_names(proto) == ["kp", "ki"]
        assert get_rx_field_names(proto) == ["measured"]


class TestResolveProjectFile:
    def test_resolve(self):
        result = resolve_project_file("/tmp/my_project", "manifests/project_manifest.yaml")
        assert str(result) == "/tmp/my_project/manifests/project_manifest.yaml"


class TestConfigBundle:
    def test_project_dir_path(self, temp_project):
        bundle = load_project(temp_project)
        assert isinstance(bundle.project_dir, Path)
        assert str(bundle.project_dir) == str(temp_project)


class TestProjectManifestRuntimeDefaults:
    def test_defaults_when_omitted(self):
        manifest = ProjectManifest(
            project_name="test",
            description="test",
            backend={"type": "sim"},
        )
        assert manifest.runtime.daemon_host == "127.0.0.1"
        assert manifest.runtime.daemon_port == 8765
        assert manifest.recording.default_run_name == "default_run"
        assert manifest.windows.default_duration_s == 3.0
