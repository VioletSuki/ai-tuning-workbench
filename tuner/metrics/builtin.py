"""Built-in generic metrics — no business-domain semantics.

Each function accepts a pandas DataFrame and optional ``columns`` list,
and returns a JSON-serialisable dict.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _resolve_columns(df: pd.DataFrame, columns: list[str] | None) -> list[str]:
    """Return the columns to operate on — only numeric columns with data."""
    if len(df) == 0:
        return []
    if columns is not None:
        return [c for c in columns if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
    return [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]


def min_max(df: pd.DataFrame, columns: list[str] | None = None) -> dict[str, dict[str, float]]:
    """Compute min and max for each selected column.

    Returns
    -------
    dict
        ``{"<col>": {"min": …, "max": …}, …}``
    """
    cols = _resolve_columns(df, columns)
    return {c: {"min": float(df[c].min()), "max": float(df[c].max())} for c in cols}


def mean(df: pd.DataFrame, columns: list[str] | None = None) -> dict[str, float]:
    """Compute arithmetic mean for each selected column."""
    cols = _resolve_columns(df, columns)
    return {c: float(df[c].mean()) for c in cols}


def std(df: pd.DataFrame, columns: list[str] | None = None) -> dict[str, float]:
    """Compute standard deviation for each selected column."""
    cols = _resolve_columns(df, columns)
    return {c: float(df[c].std()) for c in cols}


# -- builtin name -> function map --------------------------------------------

_BUILTIN_REGISTRY: dict[str, Any] = {
    "min_max": min_max,
    "mean": mean,
    "std": std,
}


def compute_builtin_metrics(
    df: pd.DataFrame,
    builtin_specs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run a list of builtin metric specifications against *df*.

    Each element in *builtin_specs* should have at least a ``"name"`` key
    (one of ``min_max``, ``mean``, ``std``) and an optional ``"columns"``
    key (a list of column names).

    Returns a dict keyed by builtin name.
    """
    result: dict[str, Any] = {}
    for spec in builtin_specs:
        name = spec.get("name")
        if name not in _BUILTIN_REGISTRY:
            raise ValueError(f"Unknown builtin metric {name!r}; known: {list(_BUILTIN_REGISTRY)}")
        fn = _BUILTIN_REGISTRY[name]
        columns = spec.get("columns")
        result[name] = fn(df, columns=columns)
    return result
