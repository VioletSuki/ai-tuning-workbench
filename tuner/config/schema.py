"""Pydantic v2 schemas for project, protocol, and metrics manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class BackendConfig(BaseModel):
    """Backend connection configuration."""

    type: Literal["serial", "mock", "sim"]
    port: Optional[str] = None
    baudrate: Optional[int] = None
    bytesize: Optional[int] = None
    parity: Optional[str] = None
    stopbits: Optional[int] = None
    timeout_s: Optional[float] = None
    mock: Optional[dict] = None


class RuntimeConfig(BaseModel):
    """Daemon runtime configuration."""

    daemon_host: str = "127.0.0.1"
    daemon_port: int = 8765
    ring_buffer_seconds: float = 60.0
    raw_log_enabled: bool = True
    decoded_log_enabled: bool = True


class RecordingConfig(BaseModel):
    """Recording defaults configuration."""

    default_run_name: str = "default_run"
    max_cli_points: int = 200
    max_cli_raw_frames: int = 100


class WindowsConfig(BaseModel):
    """Window slicing configuration."""

    default_duration_s: float = 3.0


class ProjectManifest(BaseModel):
    """Top-level project manifest."""

    project_name: str
    description: str
    backend: BackendConfig
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)
    windows: WindowsConfig = Field(default_factory=WindowsConfig)


FIELD_TYPES = Literal["uint8", "int8", "uint16", "int16", "uint32", "int32", "float32"]

_ALLOWED_FIELD_TYPES: set[str] = {
    "uint8", "int8", "uint16", "int16", "uint32", "int32", "float32",
}


class FieldSpec(BaseModel):
    """Specification of a single field in a frame payload."""

    name: str
    type: str
    wire_scale: float = 1.0
    min: Optional[float] = None
    max: Optional[float] = None
    default: Optional[float] = None
    description: Optional[str] = None
    max_delta_percent_soft: Optional[float] = None

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in _ALLOWED_FIELD_TYPES:
            raise ValueError(
                f"Unsupported field type '{v}'; must be one of {sorted(_ALLOWED_FIELD_TYPES)}"
            )
        return v


class FrameSpec(BaseModel):
    """Specification of a single frame (TX or RX)."""

    header: str
    tail: str
    message_id: str
    checksum: str = "sum_u8"
    endian: Literal["big", "little"] = "big"
    payload: list[FieldSpec]

    @field_validator("payload")
    @classmethod
    def _payload_non_empty(cls, v: list[FieldSpec]) -> list[FieldSpec]:
        if not v:
            raise ValueError("payload must not be empty")
        return v


class ProtocolManifest(BaseModel):
    """Protocol manifest describing frame encoding/decoding."""

    mode: Literal["fixed_binary"] = "fixed_binary"
    display: str = "hex"
    tx_frame: FrameSpec
    rx_frame: FrameSpec


class MetricProfile(BaseModel):
    """A named metric profile referencing a plugin or built-in computations."""

    plugin: Optional[str] = None
    function: Optional[str] = None
    inputs: Optional[dict[str, str]] = None
    builtin: Optional[list[dict[str, Any]]] = None


class MetricsManifest(BaseModel):
    """Metrics manifest describing available metric profiles."""

    metric_profiles: dict[str, MetricProfile]


class ConfigBundle(BaseModel):
    """Aggregated configuration from all three manifests."""

    project_dir: Path
    project: ProjectManifest
    protocol: ProtocolManifest
    metrics: MetricsManifest
