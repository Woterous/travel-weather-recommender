from __future__ import annotations

import math

import pandas as pd

from service.history_analysis import score_history_monthly_row


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


def _wind_level_from_speed(speed: float) -> int:
    if speed <= 5:
        return 1
    if speed <= 11:
        return 2
    if speed <= 19:
        return 3
    if speed <= 28:
        return 4
    if speed <= 38:
        return 5
    return 6


def _weather_from_rain_probability(probability: float) -> tuple[str, str, float, int]:
    if probability >= 0.65:
        return "雨", "机器学习预测：降雨概率较高", 8.0, 1
    if probability >= 0.35:
        return "雨", "机器学习预测：可能有小雨", 2.0, 1
    if probability >= 0.18:
        return "多云", "机器学习预测：多云少雨", 0.2, 0
    return "晴", "机器学习预测：晴或少云", 0.0, 0


class WeatherKnnForecastModel:
    def __init__(self, history_df: pd.DataFrame, neighbors: int = 5) -> None:
        self.neighbors = neighbors
        self.samples = self._build_samples(history_df)

    def _build_samples(self, history_df: pd.DataFrame) -> list[dict]:
        if history_df.empty:
            return []
        samples = []
        for row in history_df.to_dict("records"):
            samples.append(
                {
                    "city_slug": row.get("city_slug"),
                    "city_name": row.get("city_name"),
                    "month_num": int(_safe_float(row.get("month_num"), 1)),
                    "avg_temp": _safe_float(row.get("avg_temp"), 20.0),
                    "rainy_ratio": _safe_float(row.get("rainy_ratio"), 0.2),
                    "temp_std": _safe_float(row.get("temp_std"), 6.0),
                    "avg_wind_speed_kmh": _safe_float(row.get("avg_wind_speed_kmh"), 12.0),
                }
            )
        return samples

    def _distance(self, city_slug: str, month_num: int, sample: dict) -> float:
        city_penalty = 0.0 if sample["city_slug"] == city_slug else 1.2
        month_gap = abs(month_num - int(sample["month_num"]))
        month_gap = min(month_gap, 12 - month_gap)
        return city_penalty + month_gap / 6.0

    def predict(self, row: dict, series_context: dict | None = None) -> dict | None:
        if not self.samples:
            return None
        date_text = str(row.get("date", "2000-01-01"))
        month_num = int(date_text.split("-")[1])
        city_slug = row.get("city_slug")
        ranked = sorted(
            ((self._distance(city_slug, month_num, sample), sample) for sample in self.samples),
            key=lambda item: item[0],
        )
        nearest = ranked[: min(self.neighbors, len(ranked))]
        weights = [1 / (distance + 0.05) for distance, _sample in nearest]
        total_weight = sum(weights)

        def weighted_average(key: str) -> float:
            return sum(weight * sample[key] for weight, (_distance, sample) in zip(weights, nearest)) / total_weight

        historical_avg_temp = weighted_average("avg_temp")
        historical_rainy_ratio = max(0.0, min(1.0, weighted_average("rainy_ratio")))
        temp_std = max(1.0, weighted_average("temp_std"))
        historical_wind_speed = max(0.0, weighted_average("avg_wind_speed_kmh"))
        context = series_context or {}
        api_avg_temp = _safe_float(row.get("avg_temp"), historical_avg_temp)
        api_baseline_temp = _safe_float(context.get("api_avg_temp_mean"), api_avg_temp)
        api_temp_delta = api_avg_temp - api_baseline_temp
        avg_temp = historical_avg_temp + api_temp_delta * 0.55
        api_precipitation = _safe_float(row.get("precipitation_mm"))
        api_rain_signal = min(1.0, api_precipitation / 8.0)
        api_rain_flag = _safe_float(row.get("rain_flag"))
        rainy_ratio = max(0.0, min(1.0, historical_rainy_ratio * 0.65 + max(api_rain_signal, api_rain_flag) * 0.35))
        api_wind_speed = _safe_float(row.get("wind_speed_kmh"), historical_wind_speed)
        wind_speed = max(0.0, historical_wind_speed * 0.6 + api_wind_speed * 0.4)
        weather_type, weather_detail, precipitation, rain_flag = _weather_from_rain_probability(rainy_ratio)
        avg_distance = sum(distance for distance, _sample in nearest) / len(nearest)
        context_penalty = min(abs(api_temp_delta) / 20.0, 0.2)
        confidence = max(0.35, min(0.95, 1 - avg_distance / 2.0 - context_penalty))

        return {
            "city_slug": row.get("city_slug"),
            "city_name": row.get("city_name"),
            "date": row.get("date"),
            "max_temp": round(avg_temp + min(temp_std, 7.0), 1),
            "min_temp": round(avg_temp - min(temp_std, 7.0), 1),
            "avg_temp": round(avg_temp, 1),
            "weather_type": weather_type,
            "weather_detail": weather_detail,
            "wind_direction": "",
            "wind_speed_kmh": round(wind_speed, 1),
            "wind_level": _wind_level_from_speed(wind_speed),
            "precipitation_mm": precipitation,
            "rain_flag": rain_flag,
            "rain_probability": round(rainy_ratio, 2),
            "aqi": row.get("aqi"),
            "source_type": "ml_weather_forecast",
            "source_name": "history KNN weather forecast + API trend calibration",
            "confidence": round(confidence, 2),
        }


def build_model_summary(history_df: pd.DataFrame) -> dict:
    suitability_model = TravelSuitabilityKnnModel(history_df)
    mae = suitability_model.evaluate_mae()
    weather_model = WeatherKnnForecastModel(history_df)
    return {
        "name": "KNN 历史天气预测模型",
        "sample_count": len(weather_model.samples),
        "mae": mae,
        "features": ["city_slug", "month_num", "avg_temp", "rainy_ratio", "avg_wind_speed_kmh"],
    }
