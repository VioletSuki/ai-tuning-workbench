# AGENTS.md — ai-tuning-workbench

## What this project is

A CLI data adapter layer that lets external AI agents interact with hardware/simulation devices through a manifest-driven protocol. It provides:

- **Device communication**: serial, mock (for testing), and simulation backends
- **Protocol codec**: fixed-binary frame encoding/decoding driven by YAML manifests
- **Experiment recording**: raw frames, decoded data, time windows, command logs
- **Data querying**: window-based queries, streaming, downsampling
- **Metrics & plotting**: plugin-based metric computation, time-series plots

**It is NOT** a PID tuner, firmware uploader, code-writer, or real-time controller.

## Architecture

```
CLI (tuner/*.py via Typer)
  │
  ▼
TunerClient (HTTP) ─── FastAPI daemon (tuner/daemon.py)
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
          Backend     Protocol     Runtime
          (serial/    (codec)      (ring buffer,
           mock/sim)               recorder,
                                   window mgr,
                                   metrics)
```

- **All commands except `serve`** are HTTP clients that talk to the daemon
- **The daemon** runs a background read loop polling the backend, feeding bytes through the codec, and appending decoded data to the ring buffer
- **Everything is manifest-driven** — no business variable names are hardcoded

## Project structure

```
ai-tuning-workbench/
├── tuner/                    # Main package
│   ├── cli.py               # Typer CLI — all user-facing commands
│   ├── daemon.py            # FastAPI app + DaemonContext + background read loop
│   ├── client.py            # HTTP client used by CLI commands
│   ├── config/
│   │   ├── schema.py        # Pydantic v2 models for all manifests
│   │   └── loader.py        # YAML loading → ConfigBundle
│   ├── backends/
│   │   ├── base.py          # Abstract Backend + create_backend() factory
│   │   ├── mock_backend.py  # Generates protocol-conformant RX frames
│   │   ├── serial_backend.py
│   │   └── sim_backend.py   # Stub
│   ├── protocol/
│   │   ├── fixed_binary.py  # FixedBinaryCodec — encode/decode frames
│   │   ├── codec.py         # Codec result types
│   │   ├── checksum.py      # Checksum implementations
│   │   └── hex_utils.py     # Hex string ↔ bytes conversion
│   ├── runtime/
│   │   ├── state.py         # RuntimeState — central state holder
│   │   ├── ring_buffer.py   # Time-windowed ring buffer for decoded data
│   │   ├── recorder.py      # Persists raw/decoded/window/command logs to disk
│   │   ├── window_manager.py
│   │   └── data_access.py   # Query helpers (get_raw, get_data, stream, downsample)
│   ├── metrics/
│   │   ├── builtin.py       # Built-in metrics (min, max, mean)
│   │   └── plugin_loader.py # Loads external metric plugins from project dir
│   ├── plotting/
│   │   ├── plotter.py       # Static plot generation (PNG)
│   │   └── live_plotter.py  # Live-updating matplotlib window
│   ├── agent/
│   │   ├── context.py       # runtime_context.json + context_pack.md generation
│   │   └── logs.py          # Command logging
│   └── utils/
│       ├── file_utils.py
│       └── time_utils.py
├── tests/                   # pytest test suite
├── examples/
│   ├── motor_pid_project/   # Mock motor PID tuning example
│   │   ├── manifests/       # project_manifest.yaml, protocol_manifest.yaml, metrics_manifest.yaml
│   │   ├── agent/           # AI guidance docs (tuning_guide.md, safety_rules.md, etc.)
│   │   ├── metrics/         # Custom metrics plugin (motor_pid_metrics.py)
│   │   └── runs/            # Runtime output directory
│   └── boiler_sim_project/  # Mock boiler temperature control example
└── pyproject.toml
```

## How to work with this project

### Install and run

```bash
conda create -n agent_tuner_v01 python=3.11 -y
conda activate agent_tuner_v01
pip install -e .
```

### Start the daemon

**`tuner serve` is a blocking foreground process** — it runs the daemon and never returns until you kill it. Do NOT run it inline with other commands:

```bash
# WRONG — serve blocks, the rest never executes:
tuner serve --project examples/motor_pid_project
tuner set-param kp=1.0   # never reached!
```

Use one of these patterns instead:

**Option A — background the daemon:**

```bash
tuner serve --project examples/motor_pid_project &
# daemon runs in background, then:
tuner status
tuner set-param kp=1.0 ki=0.02 kd=0.01 target_speed=800 bt_if_motion_flag=1
# ...
kill %1  # shut down when done
```

**Option B — two terminals / tmux panes:**

```bash
# Terminal 1 (or tmux pane 1)
tuner serve --project examples/motor_pid_project

# Terminal 2 (or tmux pane 2)
tuner set-param kp=1.0 ki=0.02 kd=0.01 target_speed=800 bt_if_motion_flag=1
# ...
```

### End-to-end tuning loop

A complete tuning cycle follows this pattern:

```
1. set-param     →  apply a set of parameter values
2. mark-window-start →  begin a time window
3. wait             →  let the system settle (typically 2–5 seconds)
4. mark-window-end  →  close the window
5. eval-window      →  compute metrics (mean_abs_error, overshoot, etc.)
6. Analyze          →  compare metrics against the tuning objective
7. set-param     →  adjust parameters based on analysis
       ↓
   repeat steps 2–7 until metrics meet the objective
```

In CLI terms:

```bash
tuner set-param kp=1.0 ki=0.02 kd=0.01 target_speed=800 bt_if_motion_flag=1
tuner mark-window-start --tag trial_001
tuner wait --seconds 3
tuner mark-window-end
tuner eval-window --window latest --metrics default --json
# → {"mean_abs_error": 45.2, "overshoot_percent": 12.1, ...}
# analyze: overshoot too high → reduce kp
tuner set-param kp=0.8
tuner mark-window-start --tag trial_002
# ... repeat
```

### Run tests

```bash
pytest                          # Run all tests
pytest tests/test_cli_basic.py  # Run a specific test file
pytest -k "TestParseNameValue"  # Run matching test class/func
```

### Key conventions

1. **No hardcoded business variables**: All parameter names, field specs, and variable mappings come from YAML manifests. The protocol codec, daemon, and CLI must never reference specific variable names like `kp`, `ki`, `target_speed` in logic — only in manifests, examples, and tests.

2. **Manifest-driven**: Every project needs three YAML files under `manifests/`:
   - `project_manifest.yaml` — backend type, runtime config, recording defaults
   - `protocol_manifest.yaml` — TX/RX frame specs (header, tail, payload fields, checksum)
   - `metrics_manifest.yaml` — metric profiles referencing plugins or built-in functions

3. **Pydantic v2 for all config**: `tuner/config/schema.py` defines all models. Field validation uses `@field_validator`.

4. **Typer for CLI**: `tuner/cli.py` uses `typer` (not `click` or `argparse`). Every command calls `TunerClient` HTTP methods.

5. **FastAPI test patterns**: Tests use `fastapi.testclient.TestClient` for daemon endpoint tests, `typer.testing.CliRunner` for CLI tests.

6. **Python 3.10+** with `from __future__ import annotations` throughout.

### Adding a new feature

1. If adding a **CLI command**: add a `@app.command()` in `tuner/cli.py`, add the corresponding method in `tuner/client.py`, and add the endpoint in `tuner/daemon.py`.
2. If adding **protocol support**: work in `tuner/protocol/` — never hardcode field names.
3. If adding a **backend**: subclass `Backend` in `tuner/backends/base.py`, implement `open/close/read_available/write`.
4. If adding **metrics**: either add built-in functions to `tuner/metrics/builtin.py` or create a plugin Python file referenced from a project's `metrics_manifest.yaml`.

### Common pitfalls

- **`tuner serve` blocks forever.** It must be started in the background (`&`), in a separate terminal, or in its own tmux pane. All other `tuner` commands are non-blocking HTTP calls that depend on the daemon being alive.
- The daemon must be running before any CLI command (except `serve` and `--help`) will work. Commands gracefully report "Daemon is not running" on connection failure.
- Backend `write()` raises `RuntimeError("Backend not open")` when called on a closed backend.
- `mark-window-end` raises `RuntimeError` if no window start was marked.
- `set-param` validates parameter names against the TX frame payload fields in the protocol manifest.
- The mock backend generates synthetic RX frames conforming to the protocol manifest — no hardware needed.
