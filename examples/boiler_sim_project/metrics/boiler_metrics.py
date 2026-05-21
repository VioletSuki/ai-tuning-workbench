"""Boiler temperature metrics plugin — evaluates temperature tracking performance."""


def compute_metrics(df, config=None):
    """Compute temperature-tracking metrics from a telemetry window.

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
    target_col = inputs.get("target", "target_temperature")
    measured_col = inputs.get("measured", "measured_temperature")
    output_col = inputs.get("output", "heater_power")

    n = len(df)
    if n == 0:
        return {
            "mean_abs_error": None,
            "max_abs_error": None,
            "final_error": None,
            "rise_time_s": None,
            "steady_state_ripple": None,
            "sample_count": 0,
        }

    target = df[target_col].astype(float)
    measured = df[measured_col].astype(float)
    error = target - measured

    mean_abs_error = float(error.abs().mean())
    max_abs_error = float(error.abs().max())
    final_error = float(error.iloc[-1])

    # Rise time: time to first reach 90% of target
    initial_target = float(target.iloc[0])
    rise_time_s = None
    if initial_target > 0:
        threshold = 0.9 * initial_target
        above = measured >= threshold
        if above.any():
            idx = above.idxmax()
            rise_time_s = round(float(df.iloc[idx].get("time_ms", 0)) / 1000.0, 2)

    # Steady-state ripple: standard deviation of last 10 readings
    if n >= 10:
        steady_ripple = float(measured.iloc[-10:].std())
    else:
        steady_ripple = float(measured.std()) if n > 1 else 0.0

    result = {
        "mean_abs_error": round(mean_abs_error, 2),
        "max_abs_error": round(max_abs_error, 2),
        "final_error": round(final_error, 2),
        "rise_time_s": rise_time_s,
        "steady_state_ripple": round(steady_ripple, 2),
        "sample_count": n,
    }

    return result
