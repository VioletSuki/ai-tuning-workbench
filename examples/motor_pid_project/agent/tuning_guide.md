# Tuning Guide — motor_pid_project

## Parameter Reference

| Param | Unit | Scale | Typical Range | Effect |
|---|---|---|---|---|
| kp | gain | 1000 | 500–5000 | Proportional — higher = faster response, more overshoot |
| ki | gain | 1000 | 0–500 | Integral — eliminates steady-state error, can cause oscillation |
| kd | gain | 1000 | 0–200 | Derivative — dampens overshoot, sensitive to noise |
| target_speed | RPM | 1 | 200–2000 | Desired motor speed |
| bt_if_motion_flag | flag | 1 | 0 or 1 | Enable/disable motion |

## Common Strategies

1. **Increase kp** if the measured speed is far below target and response is sluggish.
2. **Increase ki** if steady-state error persists after kp adjustment.
3. **Increase kd** if overshoot is excessive after kp/ki adjustment.
4. **Reduce all gains** if oscillation is present (oscillation_score > 0.1).
