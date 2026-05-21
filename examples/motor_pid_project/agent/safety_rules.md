# Safety Rules — motor_pid_project

**Always follow these rules in order before making changes:**

1. **Before analysis**: If the motor may be running, stop it first:
   ```
   tuner set-param bt_if_motion_flag=0 target_speed=0
   ```
2. **Before large gain changes**: Set bt_if_motion_flag=0, apply gains, then re-enable.
3. **Never exceed**: kp > 5000, ki > 1000, kd > 500 without explicit human confirmation.
4. **Monitor after each parameter change**: Record a 3-second window and evaluate metrics before proceeding.
5. **If oscillation is detected** (oscillation_score > 0.1): immediately recommend setting bt_if_motion_flag=0 and reducing gains by 50%.
