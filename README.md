# ai-tuning-workbench

CLI data adapter layer for external AI agents.

## What this project is

- Serial / simulation communication tool
- Manifest-driven variable encode / decode tool
- Experiment data recording tool
- Windowed data query tool
- Metrics computation and plotting tool
- CLI data adapter layer for external AI agents

## What this project is NOT

- PID-specific parameter tuner
- Auto-flasher / firmware uploader
- Auto code-writing tool
- Full Agent IDE
- Real-time inner-loop controller

## Installation

```bash
conda create -n agent_tuner_v01 python=3.11 -y
conda activate agent_tuner_v01
cd ai-tuning-workbench
pip install -e .
```

## CLI overview (target)

```
tuner serve --project examples/motor_pid_project
tuner status
tuner send-hex "AA 10 ... FF"
tuner set-param name=value name2=value2
tuner get-current-params
tuner start-record --tag test_001
tuner stop-record
tuner mark-window-start --tag trial_001
tuner mark-window-end
tuner wait --seconds 3
tuner get-raw --last 2s --max-frames 50
tuner get-data --last 3s --vars all --max-points 100 --json
tuner stream --vars a,b --interval 0.1s --duration 2s --max-lines 50
tuner eval-window --last 3s --metrics default --json
tuner plot --last 5s --x time_ms --y a,b --save
tuner get-runtime-context --json
tuner get-summary --latest
```

## Key concepts

### `runtime_context.json`

A machine-readable snapshot of the current runtime state — active parameters, run directory, ring buffer stats, latest window, latest metrics, command log. Intended for programmatic consumption by external agents.

### `context_pack.md`

A human-readable Markdown summary bundling the same runtime context plus any AI-oriented guidance (tuning objective, safety rules, command reference) from the project's `agent/` directory. Intended to be pasted into an AI agent's context window.

## Example projects

Two example projects are provided:

| Project | Domain | Backend | Variables |
|---|---|---|---|
| `examples/motor_pid_project` | Motor speed PID tuning | mock | kp, ki, kd, target_speed, measured_speed, pwm, bt_if_motion_flag |
| `examples/boiler_sim_project` | Boiler temperature control | mock | target_temperature, measured_temperature, heater_power, heater_enabled |

Both use the mock backend — no hardware required. Each project includes manifests, a metrics plugin, and AI-agent guidance documents.

### Quick start (mock backend)

```bash
conda activate agent_tuner_v01
cd ai-tuning-workbench
pip install -e .

# Terminal 1: start the daemon
tuner serve --project examples/motor_pid_project

# Terminal 2: run the tuning workflow
tuner status
tuner set-param kp=1.0 ki=0.02 kd=0.01 target_speed=800 bt_if_motion_flag=1
tuner mark-window-start --tag trial_001
tuner wait --seconds 3
tuner set-param bt_if_motion_flag=0 target_speed=0
tuner mark-window-end
tuner eval-window --window latest --metrics default --json
tuner plot --window latest --x time_ms --y target_speed,measured_speed --save
tuner get-data --window latest --vars time_ms,target_speed,measured_speed,pwm --max-points 20 --json
```

Expected output:
- `set-param` prints the hex frame sent to the (mock) device
- `eval-window` returns JSON metrics (mean_abs_error, overshoot_percent, etc.)
- `plot` saves a PNG to the current run directory
- `runs/` contains complete raw/decoded/window/agent records

### Boiler example

```bash
tuner serve --project examples/boiler_sim_project
# in another terminal:
tuner set-param target_temperature=100 heater_enabled=1
tuner mark-window-start --tag warmup
tuner wait --seconds 5
tuner mark-window-end
tuner eval-window --window latest --metrics default --json
```

## v0.1 boundaries

- Backend: mock and serial supported; simulation backend is a stub
- Protocol: fixed-binary frame mode only (header/tail/checksum/payload)
- Metrics: built-in min/max/mean plus plugin loader for custom Python functions
- Plotting: basic time-series line plots via matplotlib
- No real-time inner-loop control; daemon is a polling/HTTP adapter, not a hard-realtime bridge
