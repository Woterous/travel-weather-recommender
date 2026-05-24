from __future__ import annotations

import math

import pandas as pd

from service.history_analysis import build_history_baseline_lookup, score_history_monthly_row


FEATURE_RANGES = {
    "month_num": 12.0,
    "avg_temp": 40.0,
    "rainy_ratio": 1.0,
    "comfortable_days_ratio": 1.0,
    "temp_std": 15.0,
    "avg_wind_speed_kmh": 80.0,
}


def _safe_float(value, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(numeric):
        return default
    return numeric


class TravelSuitabilityKnnModel:
    def __init__(self, history_df: pd.DataFrame, neighbors: int = 5) -> None:
        self.neighbors = neighbors
        self.samples = self._build_samples(history_df)

    def _build_samples(self, history_df: pd.DataFrame) -> list[dict]:
        if history_df.empty:
            return []
        samples = []
        for row in history_df.to_dict("records"):
            target = score_history_monthly_row(row)
            samples.append(
                {
                    "features": {
                        "month_num": _safe_float(row.get("month_num")),
                        "avg_temp": _safe_float(row.get("avg_temp")),
                        "rainy_ratio": _safe_float(row.get("rainy_ratio")),
                        "comfortable_days_ratio": _safe_float(row.get("comfortable_days_ratio")),
                        "temp_std": _safe_float(row.get("temp_std")),
                        "avg_wind_speed_kmh": _safe_float(row.get("avg_wind_speed_kmh")),
                    },
                    "target": target,
                }
            )
        return samples

    def _distance(self, left: dict, right: dict) -> float:
        total = 0.0
        for key, scale in FEATURE_RANGES.items():
            total += ((_safe_float(left.get(key)) - _safe_float(right.get(key))) / scale) ** 2
        return math.sqrt(total)

    def predict(self, features: dict) -> dict:
        if not self.samples:
            return {"ml_score": None, "ml_confidence": 0.0}

        ranked = sorted(
            ((self._distance(features, sample["features"]), sample["target"]) for sample in self.samples),
            key=lambda item: item[0],
        )
        nearest = ranked[: min(self.neighbors, len(ranked))]
        weights = [1 / (distance + 0.05) for distance, _target in nearest]
        total_weight = sum(weights)
        prediction = sum(weight * target for weight, (_distance, target) in zip(weights, nearest)) / total_weight
        avg_distance = sum(distance for distance, _target in nearest) / len(nearest)
        confidence = max(0.35, min(0.95, 1 - avg_distance))
        return {"ml_score": round(prediction, 1), "ml_confidence": round(confidence, 2)}

    def evaluate_mae(self) -> float | None:
        if len(self.samples) < 2:
            return None
        errors = []
        for index, sample in enumerate(self.samples):
            others = self.samples[:index] + self.samples[index + 1 :]
            temporary = TravelSuitabilityKnnModel(pd.DataFrame(), neighbors=self.neighbors)
            temporary.samples = others
            predicted = temporary.predict(sample["features"])["ml_score"]
            if predicted is not None:
                errors.append(abs(predicted - sample["target"]))
        if not errors:
            return None
        return round(sum(errors) / len(errors), 2)


def build_forecast_ml_features(row: dict, history_baseline: dict | None) -> dict:
    month_num = int(str(row.get("date", "2000-01-01")).split("-")[1])
    history = history_baseline or {}
    avg_temp = _safe_float(row.get("avg_temp"), _safe_float(history.get("avg_temp"), 20.0))
    rain_flag = _safe_float(row.get("rain_flag"))
    wind_speed = _safe_float(row.get("wind_speed_kmh"), _safe_float(history.get("avg_wind_speed_kmh"), 12.0))
    return {
        "month_num": month_num,
        "avg_temp": avg_temp,
        "rainy_ratio": max(rain_flag, _safe_float(history.get("rainy_ratio"))),
        "comfortable_days_ratio": 1.0 if 18 <= avg_temp <= 26 else _safe_float(history.get("comfortable_days_ratio"), 0.5),
        "temp_std": _safe_float(history.get("temp_std"), 6.0),
        "avg_wind_speed_kmh": wind_speed,
    }


def predict_row_score(row: dict, history_baseline: dict | None, model: TravelSuitabilityKnnModel) -> dict:
    return model.predict(build_forecast_ml_features(row, history_baseline))


def build_model_summary(history_df: pd.DataFrame) -> dict:
    model = TravelSuitabilityKnnModel(history_df)
    mae = model.evaluate_mae()
    return {
        "name": "KNN 旅游适宜度回归模型",
        "sample_count": len(model.samples),
        "mae": mae,
        "features": list(FEATURE_RANGES.keys()),
    }
