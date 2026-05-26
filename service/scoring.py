from __future__ import annotations

from config.weights import LITERATURE_BASED_WEIGHTS_NO_AQI, LITERATURE_BASED_WEIGHTS_WITH_AQI


def _safe_float(value, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if numeric != numeric:
        return default
    return numeric


def _normalize_weights(weights: dict, aqi_available: bool) -> dict:
    working = dict(weights)
    if not aqi_available:
        working.pop("aqi", None)
    clamped = {key: min(0.40, max(0.05, value)) for key, value in working.items()}
    total = sum(clamped.values())
    return {key: round(value / total, 4) for key, value in clamped.items()}


def build_weights(preferences: dict, aqi_available: bool = False) -> dict:
    weights = dict(LITERATURE_BASED_WEIGHTS_WITH_AQI if aqi_available else LITERATURE_BASED_WEIGHTS_NO_AQI)
    if preferences["rain_sensitivity"] == "high":
        weights["rain"] += 0.08
        weights["history"] += 0.02
        weights["temperature"] -= 0.05
        weights["weather"] -= 0.05
    elif preferences["rain_sensitivity"] == "low":
        weights["rain"] -= 0.06
        weights["temperature"] += 0.03
        weights["weather"] += 0.03

    if preferences["wind_sensitivity"] == "high":
        weights["wind"] += 0.06
        weights["history"] -= 0.03
        weights["temperature"] -= 0.03
    elif preferences["wind_sensitivity"] == "low":
        weights["wind"] -= 0.03
        weights["history"] += 0.03

    if preferences["travel_style"] == "outdoor":
        weights["weather"] += 0.05
        weights["rain"] += 0.03
        weights["history"] += 0.02
        weights["temperature"] -= 0.05
        weights["wind"] -= 0.05
    elif preferences["travel_style"] == "citywalk":
        weights["history"] += 0.04
        weights["weather"] += 0.02
        weights["wind"] -= 0.03
        weights["rain"] -= 0.03
    elif preferences["travel_style"] == "seaside":
        weights["temperature"] += 0.05
        weights["wind"] += 0.05
        weights["history"] -= 0.04
        weights["weather"] -= 0.03
        weights["rain"] -= 0.03

    if aqi_available:
        if preferences["aqi_sensitivity"] == "high":
            weights["aqi"] += 0.05
            weights["temperature"] -= 0.02
            weights["history"] -= 0.02
            weights["weather"] -= 0.01
        elif preferences["aqi_sensitivity"] == "low":
            weights["aqi"] -= 0.04
            weights["temperature"] += 0.02
            weights["weather"] += 0.02

    return _normalize_weights(weights, aqi_available=aqi_available)


def score_temperature(avg_temp: float | None, preference: str) -> float:
    avg_temp = _safe_float(avg_temp)
    if avg_temp is None:
        return 50.0
    bands = {
        "cool": [(14, 22, 100), (10, 26, 82), (5, 30, 60), (-99, 99, 35)],
        "mild": [(18, 26, 100), (12, 30, 82), (5, 35, 60), (-99, 99, 40)],
        "warm": [(22, 30, 100), (18, 33, 82), (12, 36, 60), (-99, 99, 35)],
    }
    for low, high, score in bands.get(preference, bands["mild"]):
        if low <= avg_temp <= high:
            return float(score)
    return 40.0


def score_rain(row: dict, rain_sensitivity: str) -> float:
    precipitation = _safe_float(row.get("precipitation_mm"), 0.0) or 0.0
    detail = row.get("weather_detail", "")
    if precipitation >= 25 or "暴雨" in detail or "大雨" in detail:
        base = 10
    elif precipitation >= 10 or "中雨" in detail:
        base = 35
    elif precipitation >= 2 or "小雨" in detail or "阵雨" in detail:
        base = 65
    elif precipitation >= 0.1 or row.get("rain_flag"):
        base = 80
    else:
        base = 100

    if rain_sensitivity == "high" and base < 100:
        base -= 12
    elif rain_sensitivity == "low" and base < 100:
        base += 8
    return float(max(0, min(100, base)))


def score_wind(row: dict, wind_sensitivity: str, travel_style: str) -> float:
    level = _safe_float(row.get("wind_level"))
    speed = _safe_float(row.get("wind_speed_kmh"), 0.0) or 0.0
    if level is None:
        if speed <= 12:
            base = 100
        elif speed <= 28:
            base = 78
        elif speed <= 49:
            base = 55
        else:
            base = 30
    else:
        numeric_level = int(level)
        if numeric_level <= 3:
            base = 100
        elif numeric_level <= 5:
            base = 72
        else:
            base = 35

    if wind_sensitivity == "high":
        base -= 12
    elif wind_sensitivity == "low":
        base += 6
    if travel_style == "seaside" and speed >= 25:
        base -= 10
    return float(max(0, min(100, base)))


def score_weather(row: dict, travel_style: str) -> float:
    weather_type = row.get("weather_type", "未知")
    detail = row.get("weather_detail", "")
    mapping = {
        "晴": 100,
        "多云": 88,
        "阴": 72,
        "雾霾": 55,
        "雨": 50,
        "雪": 45,
        "未知": 60,
    }
    base = mapping.get(weather_type, 60)
    if "小雨" in detail:
        base = 68
    elif "中雨" in detail:
        base = 42
    elif "大雨" in detail or "暴雨" in detail:
        base = 15
    elif "雷阵雨" in detail:
        base = 30
    if travel_style == "outdoor" and weather_type == "晴":
        base += 6
    if travel_style == "citywalk" and weather_type in {"多云", "阴"}:
        base += 5
    return float(max(0, min(100, base)))


def score_history(history_baseline: dict | None) -> float:
    if not history_baseline:
        return 60.0
    comfortable_ratio = _safe_float(history_baseline.get("comfortable_days_ratio"), 0.0) or 0.0
    rainy_ratio = _safe_float(history_baseline.get("rainy_ratio"), 0.0) or 0.0
    temp_std = _safe_float(history_baseline.get("temp_std"), 0.0) or 0.0
    comfortable_component = comfortable_ratio * 55
    rain_component = (1 - rainy_ratio) * 25
    stability_component = max(0, (1 - min(temp_std, 12) / 12)) * 20
    return round(min(100, comfortable_component + rain_component + stability_component), 1)


def score_aqi(aqi_value: float | None, preference: str) -> float:
    numeric_aqi = _safe_float(aqi_value)
    if numeric_aqi is None:
        return 0.0
    if numeric_aqi <= 50:
        base = 100
    elif numeric_aqi <= 100:
        base = 85
    elif numeric_aqi <= 150:
        base = 60
    else:
        base = 30
    if preference == "high":
        base -= 10
    elif preference == "low":
        base += 5
    return float(max(0, min(100, base)))


def score_record(row: dict, history_baseline: dict | None, preferences: dict, aqi_available: bool = False) -> dict:
    weights = build_weights(preferences, aqi_available=aqi_available)
    score_parts = {
        "temperature": score_temperature(row.get("avg_temp"), preferences["temperature_preference"]),
        "rain": score_rain(row, preferences["rain_sensitivity"]),
        "wind": score_wind(row, preferences["wind_sensitivity"], preferences["travel_style"]),
        "weather": score_weather(row, preferences["travel_style"]),
        "history": score_history(history_baseline),
    }
    if aqi_available:
        score_parts["aqi"] = score_aqi(row.get("aqi"), preferences["aqi_sensitivity"])

    breakdown = {}
    total = 0.0
    for dimension, score in score_parts.items():
        weight = weights.get(dimension, 0.0)
        weighted = round(score * weight, 2)
        breakdown[dimension] = {"score": round(score, 1), "weight": weight, "weighted_score": weighted}
        total += weighted
    return {"total": round(total, 1), "weights": weights, "breakdown": breakdown}
