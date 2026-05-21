# Command Reference — motor_pid_project

```bash
# Start the daemon
tuner serve --project examples/motor_pid_project

# Check daemon status
tuner status

# Set tuning parameters
tuner set-param kp=1.0 ki=0.02 kd=0.01 target_speed=800 bt_if_motion_flag=1

# Read current parameters
tuner get-current-params

# Start/stop recording
tuner start-record --tag trial_001
tuner stop-record

# Mark a data window
tuner mark-window-start --tag trial_001
tuner wait --seconds 3
tuner mark-window-end

# Get telemetry data
tuner get-data --last 3s --vars all --max-points 50 --json

# Evaluate metrics
tuner eval-window --last 3s --metrics default --json

# Plot telemetry
tuner plot --last 5s --x time_ms --y target_speed,measured_speed --save

# Check runtime context
tuner get-runtime-context --json
tuner get-summary --latest
```
