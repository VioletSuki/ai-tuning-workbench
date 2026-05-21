# Command Reference — boiler_sim_project

```bash
tuner serve --project examples/boiler_sim_project
tuner status
tuner set-param target_temperature=100 heater_enabled=1
tuner mark-window-start --tag heatup
tuner wait --seconds 5
tuner mark-window-end
tuner eval-window --last 5s --metrics default --json
tuner get-data --last 5s --vars time_ms,measured_temperature --max-points 20
```
