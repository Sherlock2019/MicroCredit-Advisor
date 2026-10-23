# VENDORED UNCHANGED (function body) from github.com/Sherlock2019/SupplyChain_Predictions
#   path:   backend/app/forecasting.py :: _errors   (lines 62-66)
#   commit: 5c8dce6ef5cbb7b84024fe7ef6a957d5e85b765f
#   sha256 of source file: 2aafde9a0207de79ae3def973e7dd9c3f5e32790cb17e0e51c513e3e4172958c
# Only this function is vendored: the rest of the module trains XGBoost on synthetic daily sales and does not apply.
import numpy as np


def _errors(actual: np.ndarray, predicted: np.ndarray) -> dict:
    err = predicted - actual
    total = float(np.sum(actual)) or 1e-6
    return {"wape_pct": round(float(np.sum(np.abs(err)) / total * 100), 2), "bias_pct": round(float(np.sum(err) / total * 100), 2),
            "mae": round(float(np.mean(np.abs(err))), 2)}
