"""Long-running daemon with FastAPI HTTP API and background read loop.

Usage::

    python -c "from tuner.daemon import run_daemon; run_daemon('examples/motor_pid_project')"
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException

from tuner.backends.base import create_backend
from tuner.config.loader import load_project
from tuner.config.schema import ConfigBundle
from tuner.protocol.fixed_binary import FixedBinaryCodec
from tuner.metrics.plugin_loader import evaluate_window
from tuner.runtime.state import RuntimeState
from tuner.plotting.plotter import plot_query
from tuner.runtime.data_access import (
    get_raw_for_query,
    get_rows_for_query,
    stream_snapshot,
)
from tuner.utils.file_utils import append_jsonl
from tuner.utils.time_utils import utc_now_iso

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DaemonContext — wires up all runtime objects and the background read loop
# ---------------------------------------------------------------------------


class DaemonContext:
    """Container for the daemon's runtime objects and background I/O thread.

    Attributes
    ----------
    config : ConfigBundle
    codec : FixedBinaryCodec
    backend : Backend
    state : RuntimeState
    """

    def __init__(self, config: ConfigBundle) -> None:
        self.config = config
        self.codec = FixedBinaryCodec(config.protocol.model_dump())
        backend_cfg = config.project.backend
        self.backend = create_backend(
            backend_cfg.type,
            codec=self.codec,
            protocol_manifest=config.protocol.model_dump(),
            serial_config=backend_cfg.model_dump(),
            mock_config=backend_cfg.mock if backend_cfg.type == "mock" else None,
        )
        self.state = RuntimeState(config)
        self._running = False
        self._thread: threading.Thread | None = None

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Open the backend, clear state, auto-start recording, and begin the background read loop."""
        self.state.frame_index = 0
        self.state.ring_buffer.clear()
        self.state.latest_metrics = None
        self.backend.open()
        # Auto-start a recording run so that raw/decoded data and windows are persisted
        if self.state.recorder.run_dir is None:
            self.state.recorder.start_new_run()
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        logger.info(
            "Daemon started — backend=%s project=%s",
            self.config.project.backend.type,
            self.config.project.project_name,
        )

    def stop(self) -> None:
        """Stop the background loop and close the backend."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        self.backend.close()
        logger.info("Daemon stopped")

    # -- background read loop -----------------------------------------------

    def _read_loop(self) -> None:
        """Periodically poll the backend for bytes and feed them to the codec."""
        interval = 0.01  # 10 ms
        while self._running:
            try:
                data = self.backend.read_available()
                if data:
                    results = self.codec.feed(data)
                    for result in results:
                        if result.ok and result.decoded:
                            raw_meta = {
                                "raw_hex": result.hex,
                                "raw_bytes": list(result.raw),
                            }
                            self.state.append_decoded(result.decoded, raw_meta)
                        elif not result.ok:
                            logger.debug("Frame decode error: %s", result.error)
            except Exception:
                logger.exception("Read loop error")
            time.sleep(interval)

    # -- command logging ----------------------------------------------------

    def log_command(self, command: str, detail: dict[str, Any]) -> None:
        """Append a command entry to the agent command log if a run is active."""
        from tuner.agent.logs import log_command as _log_cmd

        _log_cmd(self.state.recorder, command, detail)


# ---------------------------------------------------------------------------
# FastAPI application factory
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    ctx: DaemonContext = app.state.ctx
    ctx.start()
    yield
    ctx.stop()


def create_app(config: ConfigBundle) -> FastAPI:
    """Build and return a configured FastAPI application.

    The caller is responsible for calling ``run_daemon`` or passing the
    returned app to ``uvicorn.run``.
    """
    ctx = DaemonContext(config)
    app = FastAPI(title="ai-tuning-workbench daemon", version="0.1.0", lifespan=_lifespan)
    app.state.ctx = ctx

    # -----------------------------------------------------------------------
    # GET /health
    # -----------------------------------------------------------------------
    @app.get("/health")
    async def health():
        return {"ok": True, "status": "running"}

    # -----------------------------------------------------------------------
    # GET /status
    # -----------------------------------------------------------------------
    @app.get("/status")
    async def status():
        return ctx.state.status_dict()

    # -----------------------------------------------------------------------
    # POST /send-hex
    # -----------------------------------------------------------------------
    @app.post("/send-hex")
    async def send_hex(body: dict[str, Any]):
        hex_str = body.get("hex", "")
        if not hex_str:
            raise HTTPException(400, detail="'hex' field is required")
        try:
            from tuner.protocol.hex_utils import parse_hex_string

            raw = parse_hex_string(hex_str)
        except Exception as exc:
            raise HTTPException(400, detail=f"Invalid hex string: {exc}")
        ctx.backend.write(raw)
        ctx.log_command("send-hex", {"hex": hex_str})
        return {"ok": True, "bytes_written": len(raw)}

    # -----------------------------------------------------------------------
    # POST /set-param
    # -----------------------------------------------------------------------
    @app.post("/set-param")
    async def set_param(body: dict[str, Any]):
        params: dict[str, float] = body.get("params", {})
        force: bool = body.get("force", False)

        if not params:
            raise HTTPException(400, detail="'params' dict is required")

        # Resolve TX payload field specs from the protocol manifest
        tx_fields = ctx.config.protocol.tx_frame.payload
        field_names = {f.name for f in tx_fields}

        # Validate param names
        for name in params:
            if name not in field_names:
                raise HTTPException(
                    400, detail=f"Unknown parameter {name!r}; valid: {sorted(field_names)}"
                )

        # Merge: current values + new params + manifest defaults
        merged = dict(ctx.state.current_params)
        merged.update(params)

        for field in tx_fields:
            if field.name not in merged:
                if field.default is not None:
                    merged[field.name] = field.default
                elif not force:
                    raise HTTPException(
                        400,
                        detail=f"Missing required parameter {field.name!r} "
                        f"(no default and no current value)",
                    )

        # Validate min / max
        for field in tx_fields:
            if field.name not in merged:
                continue
            val = merged[field.name]
            if field.min is not None and val < field.min:
                if force:
                    merged[field.name] = field.min
                else:
                    raise HTTPException(
                        400,
                        detail=f"Parameter {field.name!r} value {val} below min {field.min}",
                    )
            if field.max is not None and val > field.max:
                if force:
                    merged[field.name] = field.max
                else:
                    raise HTTPException(
                        400,
                        detail=f"Parameter {field.name!r} value {val} above max {field.max}",
                    )

        # Encode and write
        try:
            raw_bytes, hex_str = ctx.codec.encode_tx_frame(merged)
        except Exception as exc:
            raise HTTPException(400, detail=f"Encode error: {exc}")

        ctx.backend.write(raw_bytes)

        # Persist params
        ctx.state.current_params = dict(merged)
        ctx.log_command("set-param", {"params": merged, "hex_frame": hex_str})

        return {
            "ok": True,
            "current_params": ctx.state.current_params,
            "hex_frame": hex_str,
        }

    # -----------------------------------------------------------------------
    # GET /current-params
    # -----------------------------------------------------------------------
    @app.get("/current-params")
    async def current_params():
        return {"ok": True, "params": ctx.state.current_params}

    # -----------------------------------------------------------------------
    # POST /start-record
    # -----------------------------------------------------------------------
    @app.post("/start-record")
    async def start_record(body: dict[str, Any] = {}):
        tag = body.get("tag", None)
        if ctx.state.recorder.run_dir is not None:
            # auto-close previous run before starting a new one
            ctx.state.recorder.close_run()
        run_dir = ctx.state.recorder.start_new_run(tag=tag)
        ctx.log_command("start-record", {"tag": tag, "run_dir": str(run_dir)})
        return {"ok": True, "run_dir": str(run_dir)}

    # -----------------------------------------------------------------------
    # POST /stop-record
    # -----------------------------------------------------------------------
    @app.post("/stop-record")
    async def stop_record():
        if ctx.state.recorder.run_dir is None:
            raise HTTPException(400, detail="No active recording")
        ctx.state.recorder.close_run()
        ctx.log_command("stop-record", {})
        return {"ok": True}

    # -----------------------------------------------------------------------
    # POST /mark-window-start
    # -----------------------------------------------------------------------
    @app.post("/mark-window-start")
    async def mark_window_start(body: dict[str, Any] = {}):
        tag = body.get("tag", None)
        info = ctx.state.windows.mark_start(tag=tag)
        ctx.log_command("mark-window-start", {"tag": tag})
        return {"ok": True, "window_info": info}

    # -----------------------------------------------------------------------
    # POST /mark-window-end
    # -----------------------------------------------------------------------
    @app.post("/mark-window-end")
    async def mark_window_end():
        try:
            info = ctx.state.windows.mark_end()
        except RuntimeError as exc:
            raise HTTPException(400, detail=str(exc))
        ctx.log_command("mark-window-end", {"window_id": info.get("window_id")})
        return {"ok": True, "window_info": info}

    # -----------------------------------------------------------------------
    # POST /wait
    # -----------------------------------------------------------------------
    @app.post("/wait")
    async def wait(body: dict[str, Any] = {}):
        seconds = float(body.get("seconds", 1.0))
        if seconds <= 0 or seconds > 300:
            raise HTTPException(400, detail="seconds must be between 0 and 300")
        time.sleep(seconds)
        return {"ok": True, "slept_seconds": seconds}

    # -----------------------------------------------------------------------
    # GET  /raw
    # -----------------------------------------------------------------------
    @app.get("/raw")
    async def get_raw(
        last: str | None = None,
        window: str | None = None,
        max_frames: int | None = None,
    ):
        rows = get_raw_for_query(ctx.state, window=window, last=last, max_frames=max_frames)
        return {"ok": True, "count": len(rows), "frames": rows}

    # -----------------------------------------------------------------------
    # GET  /data
    # -----------------------------------------------------------------------
    @app.get("/data")
    async def get_data(
        last: str | None = None,
        window: str | None = None,
        vars: str | None = None,
        max_points: int | None = None,
        format: str = "json",
    ):
        rows = get_rows_for_query(
            ctx.state,
            window=window,
            last=last,
            max_points=max_points,
            vars_spec=vars or "all",
        )
        if format == "csv":
            from tuner.runtime.data_access import rows_to_csv_text

            return {"ok": True, "count": len(rows), "csv": rows_to_csv_text(rows)}
        return {"ok": True, "count": len(rows), "rows": rows}

    # -----------------------------------------------------------------------
    # GET /stream  — blocking snapshot-style stream
    # -----------------------------------------------------------------------
    @app.get("/stream")
    async def stream(
        vars: str = "all",
        interval: str = "0.1s",
        duration: str = "2s",
        max_lines: int | None = None,
    ):
        samples = await asyncio.to_thread(
            stream_snapshot,
            ctx.state,
            vars_spec=vars,
            interval=interval,
            duration=duration,
            max_lines=max_lines,
        )
        return {"ok": True, "count": len(samples), "samples": samples}

    # -----------------------------------------------------------------------
    # POST /eval-window
    # -----------------------------------------------------------------------
    @app.post("/eval-window")
    async def eval_window(body: dict[str, Any] = {}):
        window = body.get("window")
        last = body.get("last")
        metrics_profile = body.get("metrics", "default")
        try:
            result = evaluate_window(
                config_bundle=ctx.config,
                runtime_state=ctx.state,
                window=window,
                last=last,
                metrics_profile=metrics_profile,
            )
        except (ValueError, FileNotFoundError, ImportError, AttributeError) as exc:
            raise HTTPException(400, detail=str(exc))
        ctx.log_command("eval-window", {
            "window": window,
            "last": last,
            "profile": metrics_profile,
            "row_count": result.get("row_count", 0),
        })
        return result

    # -----------------------------------------------------------------------
    # POST /plot
    # -----------------------------------------------------------------------
    @app.post("/plot")
    async def plot(body: dict[str, Any] = {}):
        window = body.get("window")
        last = body.get("last")
        x = body.get("x")
        y = body.get("y")
        save = body.get("save", True)
        show = body.get("show", False)
        try:
            result = await asyncio.to_thread(
                plot_query,
                ctx.state,
                window=window,
                last=last,
                x=x,
                y=y,
                save=save,
                show=show,
            )
        except (ValueError, ImportError) as exc:
            raise HTTPException(400, detail=str(exc))
        return {"ok": True, **result}

    # -----------------------------------------------------------------------
    # GET  /runtime-context
    # -----------------------------------------------------------------------
    @app.get("/runtime-context")
    async def runtime_context():
        from tuner.agent.context import build_runtime_context, write_runtime_context

        context = build_runtime_context(ctx.config, ctx.state)
        write_runtime_context(ctx.config, ctx.state)
        return context

    # -----------------------------------------------------------------------
    # GET  /summary
    # -----------------------------------------------------------------------
    @app.get("/summary")
    async def summary(latest: bool = False):
        from tuner.agent.context import get_summary_text

        result = get_summary_text(ctx.state)
        return {"ok": True, "summary": result["summary"], "source": result["source"]}

    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_daemon(
    project: str,
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Load a project and start the FastAPI daemon (blocking).

    Parameters
    ----------
    project : str
        Path to a project directory containing ``manifests/``.
    host : str, optional
        Bind address (default from manifest or ``127.0.0.1``).
    port : int, optional
        Bind port (default from manifest or ``8765``).
    """
    config = load_project(project)
    host = host or config.project.runtime.daemon_host
    port = port or config.project.runtime.daemon_port

    app = create_app(config)
    logger.info("Starting daemon on %s:%s (project=%s)", host, port, project)
    uvicorn.run(app, host=host, port=port, log_level="info")


def start_daemon(
    project_dir: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Entry point called by the CLI ``serve`` command (Task 07)."""
    run_daemon(str(project_dir), host=host, port=port)
