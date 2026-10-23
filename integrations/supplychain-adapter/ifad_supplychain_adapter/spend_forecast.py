"""Spending-velocity forecast for project budgets, evaluated like SupplyChain_Predictions evaluates demand models:
hold out the latest periods, compare a trend model with a naive baseline (last period repeated) using the vendored
WAPE/bias/MAE metrics, and only prefer the trend model when it beats the baseline on the holdout.

Amounts are floats here because this is an illustrative projection, not an authoritative financial figure; the
budget engine's Decimal results are the figures of record.
"""
from __future__ import annotations

import numpy as np

from ifad_supplychain_adapter.vendor.forecast_metrics import _errors

ADAPTER_VERSION = "supplychain-adapter/1.0.0"
SOURCE_COMMIT = "5c8dce6ef5cbb7b84024fe7ef6a957d5e85b765f"


def _trend(train: np.ndarray, horizon: int) -> np.ndarray:
    x = np.arange(train.size, dtype=float)
    if train.size < 2:
        return np.repeat(train[-1] if train.size else 0.0, horizon)
    slope, intercept = np.polyfit(x, train, 1)
    future = np.arange(train.size, train.size + horizon, dtype=float)
    return np.maximum(0.0, slope * future + intercept)


def forecast_spending(period_spend: list[float], horizon: int, remaining_budget: float, holdout: int = 2) -> dict:
    """period_spend: actual expenditure per reporting period, oldest first."""
    series = np.asarray(period_spend, dtype=float)
    if series.size < holdout + 2:
        return {"status": "insufficient_history", "periods_available": int(series.size),
                "periods_required": holdout + 2, "method": None}
    train, test = series[:-holdout], series[-holdout:]
    trend_eval = _errors(test, _trend(train, holdout))
    naive_eval = _errors(test, np.repeat(train[-1], holdout))
    use_trend = trend_eval["wape_pct"] < naive_eval["wape_pct"]
    projection = _trend(series, horizon) if use_trend else np.repeat(series[-1], horizon)
    cumulative = np.cumsum(projection)
    exhausted = next((i + 1 for i, v in enumerate(cumulative) if v >= remaining_budget), None)
    return {
        "status": "ok", "method": "linear_trend" if use_trend else "naive_last_period",
        "holdout_periods": holdout, "trend_holdout": trend_eval, "naive_holdout": naive_eval,
        "projected_spend": [round(float(v), 2) for v in projection],
        "periods_until_budget_exhausted": exhausted,
        "note": "Illustrative projection on synthetic records; not a financial forecast of record.",
        "source": f"metrics vendored from SupplyChain_Predictions forecasting._errors @ {SOURCE_COMMIT[:7]}",
    }
