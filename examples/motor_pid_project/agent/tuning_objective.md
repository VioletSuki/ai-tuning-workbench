# Tuning Objective — motor_pid_project

## Priority Order

1. **Safety** — never exceed mechanical or electrical limits. The motor must stop (bt_if_motion_flag=0) before changing parameters that could cause runaway.
2. **Minimize overshoot** — overshoot above 10% is unacceptable.
3. **Settle time** — steady-state within 5% of target within 2 seconds.
4. **Steady-state error** — mean absolute error under 20 RPM at steady state.
5. **Smooth output** — avoid PWM oscillation; oscillation score should be < 0.1.

## Acceptance Criteria

| Metric | Target |
|---|---|
| overshoot_percent | ≤ 10% |
| mean_abs_error | ≤ 20 RPM |
| settled | true |
| oscillation_score | < 0.1 |
