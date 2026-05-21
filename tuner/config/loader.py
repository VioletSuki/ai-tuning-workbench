"""Manifest YAML loading and validation."""

from pathlib import Path
from typing import Union

import yaml

from tuner.config.schema import (
    ConfigBundle,
    MetricsManifest,
    ProjectManifest,
    ProtocolManifest,
)


def load_yaml(path: Union[str, Path]) -> dict:
    """Load a YAML file and return the parsed dict."""
    path = Path(path)
    with open(path, "r") as f:
        data: dict = yaml.safe_load(f)
    return data


def _require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing manifest file: {path}")


def load_project(project_dir: Union[str, Path]) -> ConfigBundle:
    """Load all three manifests from *project_dir* and return a validated ConfigBundle.

    Reads ``manifests/project_manifest.yaml``, ``manifests/protocol_manifest.yaml``,
    and ``manifests/metrics_manifest.yaml``. Raises ``FileNotFoundError`` if any
    manifest is missing, and lets YAML / Pydantic errors propagate on malformed content.
    """
    project_dir = Path(project_dir)

    project_path = project_dir / "manifests" / "project_manifest.yaml"
    protocol_path = project_dir / "manifests" / "protocol_manifest.yaml"
    metrics_path = project_dir / "manifests" / "metrics_manifest.yaml"

    _require_file(project_path)
    _require_file(protocol_path)
    _require_file(metrics_path)

    project_data = load_yaml(project_path)
    protocol_data = load_yaml(protocol_path)
    metrics_data = load_yaml(metrics_path)

    return ConfigBundle(
        project_dir=project_dir,
        project=ProjectManifest(**project_data),
        protocol=ProtocolManifest(**protocol_data),
        metrics=MetricsManifest(**metrics_data),
    )


def resolve_project_file(project_dir: Union[str, Path], relative_path: str) -> Path:
    """Resolve *relative_path* against a project directory."""
    return Path(project_dir) / relative_path


def get_tx_field_names(protocol: ProtocolManifest) -> list[str]:
    """Return the field names of the TX frame payload."""
    return [f.name for f in protocol.tx_frame.payload]


def get_rx_field_names(protocol: ProtocolManifest) -> list[str]:
    """Return the field names of the RX frame payload."""
    return [f.name for f in protocol.rx_frame.payload]
