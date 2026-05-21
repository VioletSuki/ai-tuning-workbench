"""Agent runtime context and summary generation.

Provides structured machine-readable context snapshots for external AI Agents.
No large telemetry arrays or natural-language summaries are generated here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tuner.config.schema import ConfigBundle
from tuner.runtime.state import RuntimeState


def build_runtime_context(
    config_bundle: ConfigBundle,
    runtime_state: RuntimeState,
) -> dict[str, Any]:
    """Assemble a runtime-context dict from the current configuration and state.

    The returned dict is JSON-serialisable and compact — no telemetry data
    arrays are included.

    Fields
    ------
    project_name : str
    backend : str
        Backend type (``mock``, ``serial``, ``sim``).
    connection : str
        Always ``"connected"`` while the daemon runs (no heartbeat yet).
    current_params : dict
        Current TX parameter values.
    tx_params : dict
        Descriptors (min, max, default, description) derived from the protocol
        manifest — **not** from hardcoded business variables.
    rx_channels : list[str]
        RX field names derived from the protocol manifest.
    latest_data_time : str | None
        ISO-8601 timestamp of the most recently decoded frame.
    latest_metrics : dict | None
        Most recent metrics result.
    available_commands : list[str]
        Commands the agent can invoke via CLI/HTTP.
    """
    project = config_bundle.project
    protocol = config_bundle.protocol

    # Derive TX param descriptors from the manifest (no business variables)
    tx_params: dict[str, dict[str, Any]] = {}
    for field in protocol.tx_frame.payload:
        desc: dict[str, Any] = {}
        if field.min is not None:
            desc["min"] = field.min
        if field.max is not None:
            desc["max"] = field.max
        if field.default is not None:
            desc["default"] = field.default
        if field.description is not None:
            desc["description"] = field.description
        tx_params[field.name] = desc

    # Derive RX channel names from the manifest
    rx_channels = [f.name for f in protocol.rx_frame.payload]

    available_commands = [
        "send-hex",
        "set-param",
        "get-raw",
        "get-data",
        "stream",
        "eval-window",
        "plot",
        "mark-window-start",
        "mark-window-end",
    ]

    return {
        "project_name": project.project_name,
        "backend": project.backend.type,
        "connection": "connected",
        "current_params": dict(runtime_state.current_params),
        "tx_params": tx_params,
        "rx_channels": rx_channels,
        "latest_data_time": runtime_state.latest_data_time,
        "latest_metrics": runtime_state.latest_metrics,
        "available_commands": available_commands,
    }


def write_runtime_context(
    config_bundle: ConfigBundle,
    runtime_state: RuntimeState,
) -> Path | None:
    """Build and persist ``runtime_context.json`` under the active run directory.

    Returns the file path, or ``None`` if no run is active.
    """
    if runtime_state.recorder.run_dir is None:
        return None
    context = build_runtime_context(config_bundle, runtime_state)
    return runtime_state.recorder.write_runtime_json("runtime_context.json", context)


def get_summary_text(
    runtime_state: RuntimeState,
) -> dict[str, Any]:
    """Retrieve a summary text file from the run or project directory.

    Resolution priority (first match wins):

    1. ``runs/<run>/runtime/ai_summary.md``
    2. ``runs/<run>/runtime/context_pack.md``
    3. ``<project>/agent/context_pack.md``
    4. No file found → ``{"summary": "summary not available", "source": None}``

    No external AI API is called.
    """
    if runtime_state.recorder.run_dir is None:
        return {"summary": "summary not available", "source": None}

    runtime_dir = runtime_state.recorder.run_dir / "runtime"
    project_agent_dir = runtime_state.config.project_dir / "agent"

    candidates = [
        ("runtime/ai_summary.md", runtime_dir / "ai_summary.md"),
        ("runtime/context_pack.md", runtime_dir / "context_pack.md"),
        ("project/agent/context_pack.md", project_agent_dir / "context_pack.md"),
    ]

    for label, path in candidates:
        if path.exists():
            return {
                "summary": path.read_text(encoding="utf-8"),
                "source": str(path),
            }

    return {"summary": "summary not available", "source": None}
