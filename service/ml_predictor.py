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
    def __init__(
        self,
        history_df: pd.DataFrame,
        history_monthly_df: pd.DataFrame | None = None,
        neighbors: int = 9,
    ) -> None:
        self.neighbors = neighbors
        if "date" in history_df.columns:
            daily_df = history_df
            monthly_df = history_monthly_df if history_monthly_df is not None else pd.DataFrame()
        else:
            daily_df = pd.DataFrame()
            monthly_df = history_monthly_df if history_monthly_df is not None else history_df
        self.daily_samples = self._build_daily_samples(daily_df)
        self.monthly_samples = self._build_monthly_samples(monthly_df)
        self.samples = self.daily_samples or self.monthly_samples
        self.daily_by_city = self._group_samples_by_city(self.daily_samples)
        self.monthly_by_city = self._group_samples_by_city(self.monthly_samples)
        self.recent_daily_cache = {
            city_slug: self._build_recent_daily_stats(samples)
            for city_slug, samples in self.daily_by_city.items()
        }
        self.recent_monthly_cache = {
            city_slug: self._build_recent_monthly_stats(samples)
            for city_slug, samples in self.monthly_by_city.items()
        }
        self.seasonal_average_cache: dict[tuple[str, int, str], float | None] = {}

    def _group_samples_by_city(self, samples: list[dict]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for sample in samples:
            grouped.setdefault(str(sample.get("city_slug")), []).append(sample)
        for city_samples in grouped.values():
            city_samples.sort(key=lambda sample: sample.get("date") or str(sample.get("month_key") or ""))
        return grouped

    def _build_daily_samples(self, history_df: pd.DataFrame) -> list[dict]:
        if history_df.empty:
            return []
        working = history_df.copy()
        working["date_value"] = pd.to_datetime(working.get("date"), errors="coerce")
        working = working[working["date_value"].notna()].copy()
        if working.empty:
            return []
        for column, default in [
            ("max_temp", 20.0),
            ("min_temp", 20.0),
            ("avg_temp", 20.0),
            ("rain_flag", 0.0),
            ("precipitation_mm", 0.0),
            ("avg_wind_speed_kmh", 12.0),
            ("wind_speed_kmh", 12.0),
        ]:
            if column not in working:
                working[column] = default
            working[column] = pd.to_numeric(working[column], errors="coerce").fillna(default)
        if "month_num" not in working:
            working["month_num"] = working["date_value"].dt.month
        if "day_of_year" not in working:
            working["day_of_year"] = working["date_value"].dt.dayofyear

        samples = []
        columns = [
            "city_slug",
            "city_name",
            "date_value",
            "month_num",
            "day_of_year",
            "max_temp",
            "min_temp",
            "avg_temp",
            "rain_flag",
            "precipitation_mm",
            "avg_wind_speed_kmh",
            "wind_speed_kmh",
        ]
        for row in working[columns].itertuples(index=False):
            max_temp = float(row.max_temp)
            min_temp = float(row.min_temp)
            avg_temp = float(row.avg_temp)
            samples.append(
                {
                    "city_slug": row.city_slug,
                    "city_name": row.city_name,
                    "date": row.date_value,
                    "month_num": int(_safe_float(row.month_num, row.date_value.month)),
                    "day_of_year": int(_safe_float(row.day_of_year, row.date_value.dayofyear)),
                    "avg_temp": avg_temp,
                    "temp_half_range": max(1.5, min(9.0, (max_temp - min_temp) / 2)),
                    "rain_flag": float(row.rain_flag),
                    "precipitation_mm": float(row.precipitation_mm),
                    "avg_wind_speed_kmh": float(row.avg_wind_speed_kmh),
                    "wind_speed_kmh": float(row.wind_speed_kmh),
                }
            )
        return samples

    def _build_monthly_samples(self, history_df: pd.DataFrame) -> list[dict]:
        if history_df.empty:
            return []
        samples = []
        for row in history_df.to_dict("records"):
            month_num = int(_safe_float(row.get("month_num"), 1))
            samples.append(
                {
                    "city_slug": row.get("city_slug"),
                    "city_name": row.get("city_name"),
                    "month_key": row.get("month_key"),
                    "month_num": month_num,
                    "day_of_year": min(365, max(1, int((month_num - 1) * 30.4 + 15))),
                    "avg_temp": _safe_float(row.get("avg_temp"), 20.0),
                    "temp_half_range": max(2.0, min(8.0, _safe_float(row.get("temp_std"), 5.0))),
                    "rain_flag": _safe_float(row.get("rainy_ratio"), 0.2),
                    "precipitation_mm": _safe_float(row.get("rainy_ratio"), 0.2) * 6.0,
                    "wind_speed_kmh": _safe_float(row.get("avg_wind_speed_kmh"), 12.0),
                }
            )
        return samples

    def _same_season_distance(self, city_slug: str, day_of_year: int, sample: dict) -> float:
        city_penalty = 0.0 if sample["city_slug"] == city_slug else 1.2
        day_gap = abs(day_of_year - int(sample["day_of_year"]))
        day_gap = min(day_gap, 366 - day_gap)
        return city_penalty + day_gap / 45.0

    def _build_recent_daily_stats(self, city_samples: list[dict]) -> dict:
        if len(city_samples) < 14:
            return {}
        recent_60 = city_samples[-60:]
        recent_30 = city_samples[-30:]
        recent_14 = city_samples[-14:]
        previous_14 = city_samples[-28:-14] if len(city_samples) >= 28 else []

        def avg(samples: list[dict], key: str) -> float:
            return sum(_safe_float(sample.get(key)) for sample in samples) / len(samples)

        latest_sample = city_samples[-1]
        previous_14_avg = avg(previous_14, "avg_temp") if previous_14 else avg(recent_14, "avg_temp")
        return {
            "latest_date": latest_sample["date"],
            "latest_day_of_year": int(latest_sample["day_of_year"]),
            "recent_60_avg_temp": avg(recent_60, "avg_temp"),
            "recent_30_avg_temp": avg(recent_30, "avg_temp"),
            "recent_14_avg_temp": avg(recent_14, "avg_temp"),
            "recent_temp_trend": max(-4.0, min(4.0, avg(recent_14, "avg_temp") - previous_14_avg)),
            "recent_rain_probability": max(0.0, min(1.0, avg(recent_60, "rain_flag"))),
            "recent_wind_speed": max(0.0, avg(recent_30, "wind_speed_kmh")),
        }

    def _build_recent_monthly_stats(self, city_samples: list[dict]) -> dict:
        if len(city_samples) < 2:
            return {}
        latest = city_samples[-1]
        previous = city_samples[-2]
        return {
            "latest_date": None,
            "latest_day_of_year": int(latest["day_of_year"]),
            "recent_60_avg_temp": (latest["avg_temp"] + previous["avg_temp"]) / 2,
            "recent_30_avg_temp": latest["avg_temp"],
            "recent_14_avg_temp": latest["avg_temp"],
            "recent_temp_trend": max(-4.0, min(4.0, latest["avg_temp"] - previous["avg_temp"])),
            "recent_rain_probability": max(0.0, min(1.0, (latest["rain_flag"] + previous["rain_flag"]) / 2)),
            "recent_wind_speed": max(0.0, (latest["wind_speed_kmh"] + previous["wind_speed_kmh"]) / 2),
        }

    def _seasonal_average(self, city_slug: str, day_of_year: int, key: str) -> float | None:
        cache_key = (city_slug, day_of_year, key)
        if cache_key in self.seasonal_average_cache:
            return self.seasonal_average_cache[cache_key]
        city_samples = self.daily_by_city.get(city_slug) or self.monthly_by_city.get(city_slug) or []
        if not city_samples:
            self.seasonal_average_cache[cache_key] = None
            return None
        ranked = sorted(
            (
                (self._same_season_distance(city_slug, day_of_year, sample), _safe_float(sample.get(key)))
                for sample in city_samples
            ),
            key=lambda item: item[0],
        )[: min(self.neighbors, len(city_samples))]
        weights = [1 / (distance + 0.05) for distance, _value in ranked]
        total_weight = sum(weights)
        result = sum(weight * value for weight, (_distance, value) in zip(weights, ranked)) / total_weight
        self.seasonal_average_cache[cache_key] = result
        return result

    def predict(self, row: dict, series_context: dict | None = None) -> dict | None:
        if not self.samples:
            return None
        date_text = str(row.get("date", "2000-01-01"))
        target_date = pd.to_datetime(date_text, errors="coerce")
        if pd.isna(target_date):
            return None
        day_of_year = int(target_date.dayofyear)
        city_slug = str(row.get("city_slug"))
        samples = self.daily_by_city.get(city_slug) or self.monthly_by_city.get(city_slug) or self.samples
        ranked = sorted(
            ((self._same_season_distance(city_slug, day_of_year, sample), sample) for sample in samples),
            key=lambda item: item[0],
        )
        nearest = ranked[: min(self.neighbors, len(ranked))]
        weights = [1 / (distance + 0.05) for distance, _sample in nearest]
        total_weight = sum(weights)

        def weighted_average(key: str) -> float:
            return sum(weight * sample[key] for weight, (_distance, sample) in zip(weights, nearest)) / total_weight

        historical_avg_temp = weighted_average("avg_temp")
        historical_rainy_ratio = max(0.0, min(1.0, weighted_average("rain_flag")))
        temp_half_range = max(1.0, weighted_average("temp_half_range"))
        historical_wind_speed = max(0.0, weighted_average("wind_speed_kmh"))

        recent = self.recent_daily_cache.get(city_slug) or self.recent_monthly_cache.get(city_slug) or {}
        if recent:
            seasonal_recent = self._seasonal_average(
                city_slug,
                int(recent["latest_day_of_year"]),
                "avg_temp",
            )
            seasonal_delta = historical_avg_temp - (seasonal_recent if seasonal_recent is not None else historical_avg_temp)
            horizon_days = 14
            if recent.get("latest_date") is not None:
                horizon_days = max(1, int((target_date - recent["latest_date"]).days))
            trend_factor = min(1.0, horizon_days / 14.0)
            recent_projection = (
                _safe_float(recent.get("recent_30_avg_temp"), historical_avg_temp)
                + seasonal_delta
                + _safe_float(recent.get("recent_temp_trend"), 0.0) * trend_factor * 0.45
            )
            horizon_decay = max(0.15, min(0.45, 0.45 - max(0, horizon_days - 7) / 120.0))
            avg_temp = historical_avg_temp * (1 - horizon_decay) + recent_projection * horizon_decay
            rainy_ratio = max(
                0.0,
                min(
                    1.0,
                    historical_rainy_ratio * 0.68
                    + _safe_float(recent.get("recent_rain_probability"), historical_rainy_ratio) * 0.32,
                ),
            )
            wind_speed = max(
                0.0,
                historical_wind_speed * 0.72
                + _safe_float(recent.get("recent_wind_speed"), historical_wind_speed) * 0.28,
            )
        else:
            avg_temp = historical_avg_temp
            rainy_ratio = historical_rainy_ratio
            wind_speed = historical_wind_speed

        weather_type, weather_detail, precipitation, rain_flag = _weather_from_rain_probability(rainy_ratio)
        avg_distance = sum(distance for distance, _sample in nearest) / len(nearest)
        recent_bonus = 0.08 if recent else 0.0
        confidence = max(0.35, min(0.88, 1 - avg_distance / 2.4 + recent_bonus))

        return {
            "city_slug": row.get("city_slug"),
            "city_name": row.get("city_name"),
            "date": row.get("date"),
            "max_temp": round(avg_temp + min(temp_half_range, 8.0), 1),
            "min_temp": round(avg_temp - min(temp_half_range, 8.0), 1),
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
            "source_name": "history daily KNN forecast + recent 60-day trend",
            "confidence": round(confidence, 2),
        }


def build_model_summary(history_df: pd.DataFrame, history_daily_df: pd.DataFrame | None = None) -> dict:
    daily_df = history_daily_df if history_daily_df is not None else pd.DataFrame()
    weather_model = WeatherKnnForecastModel(daily_df, history_monthly_df=history_df)
    return {
        "name": "历史日天气 KNN 预测模型",
        "sample_count": len(weather_model.samples),
        "mae": None,
        "features": ["city_slug", "day_of_year", "recent_60_days", "avg_temp", "rain_probability", "wind_speed"],
    }
