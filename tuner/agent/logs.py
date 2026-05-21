"""Agent command logging and decision trace.

Records structured machine-readable entries into the active run's ``agent/``
directory.  These logs are intended for external AI Agent consumption, not
human browsing.
"""

from __future__ import annotations

from typing import Any

from tuner.runtime.recorder import RunRecorder
from tuner.utils.time_utils import utc_now_iso


def log_command(
    recorder: RunRecorder,
    command: str,
    args: dict[str, Any],
    result: dict[str, Any] | None = None,
    ok: bool = True,
) -> None:
    """Append one command log entry to ``agent/command_log.jsonl``.

    Fields
    ------
    time : str
        ISO-8601 timestamp (utc).
    command : str
        Command name, e.g. ``"set-param"``.
    args : dict
        Command arguments (shallow, no large data arrays).
    ok : bool
        Whether the command succeeded.
    result_summary : dict
        Optional brief result summary (no full telemetry arrays).

    Does nothing if no recording run is active.
    """
    entry: dict[str, Any] = {
        "time": utc_now_iso(),
        "command": command,
        "args": args,
        "ok": ok,
    }
    if result is not None:
        entry["result_summary"] = result

    try:
        recorder.write_agent_jsonl("command_log.jsonl", entry)
    except RuntimeError:
        pass  # no active run


def log_decision_trace(
    recorder: RunRecorder,
    observation: Any = None,
    diagnosis: Any = None,
    decision: Any = None,
    action: Any = None,
    result: Any = None,
) -> None:
    """Append one decision trace entry to ``agent/decision_trace.jsonl``.

    All fields are optional and typically carry string summaries or small
    structured dicts.  Do **not** embed large telemetry arrays here.

    Fields
    ------
    time : str
        ISO-8601 timestamp.
    observation : any
        What the agent observed (e.g. metric values, stability flags).
    diagnosis : any
        Interpretation of the observation.
    decision : any
        What the agent decided to do.
    action : any
        Concrete action taken (e.g. parameter change details).
    result : any
        Brief outcome of the action.

    Does nothing if no recording run is active.
    """
    entry: dict[str, Any] = {
        "time": utc_now_iso(),
    }
    if observation is not None:
        entry["observation"] = observation
    if diagnosis is not None:
        entry["diagnosis"] = diagnosis
    if decision is not None:
        entry["decision"] = decision
    if action is not None:
        entry["action"] = action
    if result is not None:
        entry["result"] = result

    try:
        recorder.write_agent_jsonl("decision_trace.jsonl", entry)
    except RuntimeError:
        pass  # no active run
