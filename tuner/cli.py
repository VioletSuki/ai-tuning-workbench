"""Typer CLI for the ai-tuning-workbench.

All commands (except *serve*) communicate with the local daemon via HTTP.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import typer

from tuner.client import DaemonNotRunningError, TunerClient

app = typer.Typer(
    name="tuner",
    help="AI tuning workbench — CLI data adapter for external AI agents.",
    no_args_is_help=True,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _client() -> TunerClient:
    return TunerClient()


def _output(result: dict[str, Any] | list[Any] | str, json_output: bool) -> None:
    """Print *result* as JSON or as human-readable text."""
    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str, ensure_ascii=False))
        return
    if isinstance(result, dict):
        for k, v in result.items():
            typer.echo(f"{k}: {v}")
    elif isinstance(result, list):
        for item in result:
            typer.echo(str(item))
    else:
        typer.echo(str(result))


def _safe_call(
    fn, json_output: bool = False, exit_on_error: bool = True
) -> dict[str, Any] | None:
    """Execute *fn* (a client call) and handle common errors."""
    try:
        result = fn()
        _output(result, json_output)
        return result
    except DaemonNotRunningError as e:
        typer.echo(str(e), err=True)
        if exit_on_error:
            raise typer.Exit(1) from e
        return None
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        if exit_on_error:
            raise typer.Exit(1) from e
        return None


def _parse_value(s: str) -> int | float | bool | str:
    """Parse a string into int / float / bool, falling back to the raw string."""
    s = s.strip()
    # bools
    if s.lower() in ("true", "yes"):
        return True
    if s.lower() in ("false", "no"):
        return False
    # int
    try:
        return int(s)
    except ValueError:
        pass
    # float
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse_name_value(pairs: list[str]) -> dict[str, Any]:
    """Parse *key=value* pairs into a dict."""
    result: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair or pair.startswith("=") or pair.endswith("="):
            raise typer.BadParameter(
                f"Invalid format: '{pair}'. Expected name=value"
            )
        name, raw = pair.split("=", 1)
        result[name] = _parse_value(raw)
    return result


def _parse_csv(s: str | None) -> list[str] | None:
    """Parse a comma-separated string into a list, or return *None*."""
    if s is None or s.strip().lower() == "all":
        return None
    return [part.strip() for part in s.split(",") if part.strip()] or None


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


@app.command()
def serve(
    project: str = typer.Option(
        ..., "--project", help="Path to the project directory (containing manifests/)"
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Daemon bind host"),
    port: int = typer.Option(8765, "--port", help="Daemon bind port"),
) -> None:
    """Start the daemon for a project."""
    try:
        from tuner.daemon import start_daemon
    except ImportError:
        typer.echo(
            "Daemon module not available. "
            "Task 06 (daemon) must be completed before 'serve' can be used.",
            err=True,
        )
        raise typer.Exit(1) from None
    start_daemon(project_dir=Path(project), host=host, port=port)


@app.command()
def status(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show daemon status."""
    _safe_call(lambda: _client().status(), json_output=json)


@app.command("send-hex")
def send_hex(
    hex_string: str = typer.Argument(..., help="Hex string, e.g. 'AA 10 01 FF'"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Send a raw hex frame via the daemon."""
    _safe_call(lambda: _client().send_hex(hex_string), json_output=json)


@app.command("set-param")
def set_param(
    params: list[str] = typer.Argument(
        ..., help="One or more name=value pairs, e.g. param1=10.0 param2=true"
    ),
    force: bool = typer.Option(
        False, "--force", help="Bypass safety checks"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Set one or more parameters (parsed as name=value)."""
    parsed = _parse_name_value(params)
    _safe_call(lambda: _client().set_param(parsed, force=force), json_output=json)


@app.command("get-current-params")
def get_current_params(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Get the current parameter values from the daemon."""
    _safe_call(lambda: _client().get_current_params(), json_output=json)


@app.command("start-record")
def start_record(
    tag: Optional[str] = typer.Option(
        None, "--tag", help="Optional tag / run name for the recording"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Start recording telemetry data."""
    _safe_call(lambda: _client().start_record(tag=tag), json_output=json)


@app.command("stop-record")
def stop_record(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Stop recording telemetry data."""
    _safe_call(lambda: _client().stop_record(), json_output=json)


@app.command("mark-window-start")
def mark_window_start(
    tag: Optional[str] = typer.Option(
        None, "--tag", help="Optional tag for the window (e.g. trial_001)"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Mark the start of a time window."""
    _safe_call(lambda: _client().mark_window_start(tag=tag), json_output=json)


@app.command("mark-window-end")
def mark_window_end(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Mark the end of the current time window."""
    _safe_call(lambda: _client().mark_window_end(), json_output=json)


@app.command()
def wait(
    seconds: float = typer.Option(
        3.0, "--seconds", "-s", help="Duration in seconds to wait"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Wait (sleep) on the daemon side."""
    _safe_call(lambda: _client().wait(seconds), json_output=json)


@app.command("get-raw")
def get_raw(
    last: Optional[str] = typer.Option(
        None, "--last", help="Time range, e.g. '2s', '5m'"
    ),
    window: Optional[str] = typer.Option(
        None, "--window", help="Window name, e.g. 'window_0001' or 'latest'"
    ),
    max_frames: Optional[int] = typer.Option(
        None, "--max-frames", help="Maximum number of raw frames"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Get raw hex frames."""
    _safe_call(
        lambda: _client().get_raw(
            last=last, window=window, max_frames=max_frames
        ),
        json_output=json,
    )


@app.command("get-data")
def get_data(
    last: Optional[str] = typer.Option(
        None, "--last", help="Time range, e.g. '3s', '10s'"
    ),
    window: Optional[str] = typer.Option(
        None, "--window", help="Window name, e.g. 'latest'"
    ),
    vars: Optional[str] = typer.Option(
        None, "--vars", help="Comma-separated variable names, or 'all'"
    ),
    format: str = typer.Option(
        "table", "--format", help="Output format for non-JSON mode"
    ),
    max_points: Optional[int] = typer.Option(
        None, "--max-points", help="Maximum data points"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Get decoded telemetry data."""
    var_list = _parse_csv(vars)
    _safe_call(
        lambda: _client().get_data(
            last=last,
            window=window,
            vars=var_list if var_list else vars,
            format=format,
            max_points=max_points,
        ),
        json_output=json,
    )


@app.command()
def stream(
    vars: str = typer.Option(
        "all", "--vars", help="Comma-separated variable names"
    ),
    interval: str = typer.Option(
        "0.1s", "--interval", help="Snapshot interval, e.g. '0.1s', '1s'"
    ),
    duration: str = typer.Option(
        "2s", "--duration", help="Total stream duration, e.g. '2s', '5s'"
    ),
    max_lines: Optional[int] = typer.Option(
        None, "--max-lines", help="Maximum lines to output"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Stream recent telemetry snapshots."""
    var_list = _parse_csv(vars)
    _safe_call(
        lambda: _client().stream_snapshot(
            vars=var_list if var_list else vars,
            interval=interval,
            duration=duration,
            max_lines=max_lines,
        ),
        json_output=json,
    )


@app.command("eval-window")
def eval_window(
    last: Optional[str] = typer.Option(
        None, "--last", help="Time range, e.g. '3s'"
    ),
    window: Optional[str] = typer.Option(
        None, "--window", help="Window name, e.g. 'latest'"
    ),
    metrics: str = typer.Option(
        "default", "--metrics", help="Metrics profile name"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Evaluate metrics on a telemetry window."""
    _safe_call(
        lambda: _client().eval_window(
            last=last, window=window, metrics=metrics
        ),
        json_output=json,
    )


@app.command()
def plot(
    last: Optional[str] = typer.Option(
        None, "--last", help="Time range, e.g. '5s'"
    ),
    window: Optional[str] = typer.Option(
        None, "--window", help="Window name, e.g. 'latest'"
    ),
    x: str = typer.Option("time_ms", "--x", help="X-axis variable name"),
    y: str = typer.Option(
        ..., "--y", help="Comma-separated Y-axis variable names"
    ),
    save: bool = typer.Option(False, "--save", help="Save plot to file"),
    show: bool = typer.Option(False, "--show", help="Show plot window"),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Generate a plot from telemetry data."""
    y_list = _parse_csv(y)
    _safe_call(
        lambda: _client().plot(
            last=last,
            window=window,
            x=x,
            y=y_list if y_list else y,
            save=save,
            show=show,
        ),
        json_output=json,
    )


@app.command("liveplot")
def liveplot(
    x: str = typer.Option(
        "host_monotonic", "--x", help="X-axis variable name"
    ),
    y: str = typer.Option(
        ..., "--y", help="Comma-separated Y-axis variable names"
    ),
    auto_scale_y: bool = typer.Option(
        True, "--auto-scale-y/--no-auto-scale-y",
        help="Auto-scale Y-axis as data arrives (default: True)",
    ),
) -> None:
    """Open a live-updating plot window (for the user, not the agent)."""
    from tuner.plotting.live_plotter import plot_live

    client = _client()
    y_list = _parse_csv(y)

    def _fetch() -> list[dict[str, Any]]:
        result = client.get_data(last="5s")
        return result.get("rows", [])

    plot_live(
        fetch_data=_fetch,
        x=x,
        y=y_list if y_list else [],
        title=f"Live: {', '.join(y_list if y_list else [y])} vs {x}",
        auto_scale_y=auto_scale_y,
    )


@app.command("get-runtime-context")
def get_runtime_context(
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Get the current runtime context."""
    _safe_call(lambda: _client().get_runtime_context(), json_output=json)


@app.command("get-summary")
def get_summary(
    latest: bool = typer.Option(
        False, "--latest", help="Return only the latest summary"
    ),
    json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Get experiment summaries."""
    _safe_call(lambda: _client().get_summary(latest=latest), json_output=json)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
