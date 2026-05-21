# Tuning Guide — boiler_sim_project

| Param | Unit | Range | Description |
|---|---|---|---|
| target_temperature | °C | 0–200 | Desired boiler temperature |
| heater_enabled | flag | 0/1 | Enable heater |

The system uses an internal control loop. Adjust target_temperature gradually. Monitor measured_temperature trend before making further changes.
