"""Adapter around reusable SupplyChain_Predictions pieces: forecast-error metrics and the holdout-vs-naive-baseline
evaluation discipline, applied to project spending velocity."""
from ifad_supplychain_adapter.spend_forecast import ADAPTER_VERSION, SOURCE_COMMIT, forecast_spending

__all__ = ["ADAPTER_VERSION", "SOURCE_COMMIT", "forecast_spending"]
