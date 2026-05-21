# Safety Rules — boiler_sim_project

1. Set heater_enabled=0 before changing target_temperature by more than 20°C.
2. Never set target_temperature above 200°C.
3. If measured_temperature exceeds 210°C, immediately set heater_enabled=0.
