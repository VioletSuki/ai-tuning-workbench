"""Motor PID metrics plugin — evaluates speed-tracking performance."""

import math


def compute_metrics(df, config=None):
    """Compute speed-tracking metrics from a telemetry window.

    Parameters
    ----------
    df : pandas.DataFrame
        Telemetry data with columns corresponding to the metric profile ``inputs``.
    config : dict or None
        Metric profile config; ``config["inputs"]`` maps logical names to columns.

    Returns
    -------
    dict
        JSON-serializable metrics dict.
    """
    inputs = (config or {}).get("inputs", {})
    target_col = inputs.get("target", "target_speed")
    measured_col = inputs.get("measured", "measured_speed")
    output_col = inputs.get("output", "pwm")

    n = len(df)
    if n == 0:
        return {
            "mean_abs_error": None,
            "max_abs_error": None,
            "final_error": None,
            "overshoot_percent": None,
            "oscillation_score": None,
            "settled": None,
            "sample_count": 0,
        }

    target = df[target_col].astype(float)
    measured = df[measured_col].astype(float)
    error = target - measured

    mean_abs_error = float(error.abs().mean())
    max_abs_error = float(error.abs().max())
    final_error = float(error.iloc[-1])

    # Overshoot: max positive deviation from target at the start
    initial_target = float(target.iloc[0])
    if initial_target > 0:
        max_measured = float(measured.max())
        overshoot = max(0.0, (max_measured - initial_target) / initial_target * 100.0)
    else:
        overshoot = 0.0

    # Oscillation score: count sign changes in error derivative
    if n >= 3:
        deriv = error.diff().dropna()
        sign_changes = ((deriv * deriv.shift(1)) < 0).sum()
        oscillation_score = round(sign_changes / max(n - 2, 1), 4)
    else:
        oscillation_score = 0.0

    # Settled: true if final |error| < 5% of initial target
    if abs(initial_target) > 0:
        settled = abs(final_error) / abs(initial_target) < 0.05
    else:
        settled = abs(final_error) < 1.0

    result = {
        "mean_abs_error": round(mean_abs_error, 2),
        "max_abs_error": round(max_abs_error, 2),
        "final_error": round(final_error, 2),
        "overshoot_percent": round(overshoot, 2),
        "oscillation_score": oscillation_score,
        "settled": bool(settled),
        "sample_count": n,
    }

    return result
