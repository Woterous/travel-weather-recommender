from __future__ import annotations

import pandas as pd

from service.history_analysis import build_history_baseline_lookup
from service.ml_predictor import WeatherKnnForecastModel, build_model_summary
from service.reason_generator import generate_reason, generate_summary
from service.scoring import build_weights, score_record


label_map = {
    "temperature": "温度",
    "rain": "降雨",
    "wind": "风力",
    "weather": "天气类型",
    "history": "历史稳定性",
    "aqi": "AQI",
}


def _month_from_date(date_text: str) -> int:
    return int(date_text.split("-")[1])


def build_ranked_records(
    forecast_df: pd.DataFrame,
    history_df: pd.DataFrame,
    preferences: dict,
    aqi_available: bool,
    history_daily_df: pd.DataFrame | None = None,
) -> list[dict]:
    if forecast_df.empty:
        return []
    baseline_lookup = build_history_baseline_lookup(history_df)
    ml_weather_model = WeatherKnnForecastModel(
        history_daily_df if history_daily_df is not None else pd.DataFrame(),
        history_monthly_df=history_df,
    )
    scored_rows = []
    for row in forecast_df.to_dict("records"):
        history_baseline = baseline_lookup.get((row["city_slug"], _month_from_date(row["date"])))
        score_card = score_record(row, history_baseline, preferences, aqi_available=aqi_available)
        ml_weather = ml_weather_model.predict(row)
        ml_score_card = (
            score_record(ml_weather, history_baseline, preferences, aqi_available=aqi_available)
            if ml_weather
            else None
        )
        rule_score = score_card["total"]
        ml_score = ml_score_card["total"] if ml_score_card else None
        final_score = ml_score if ml_score is not None else rule_score
        reason = generate_reason(row, score_card["breakdown"], preferences, history_baseline)
        scored_rows.append(
            {
                **row,
                "score_total": final_score,
                "rule_score": rule_score,
                "ml_score": ml_score,
                "ml_confidence": ml_weather["confidence"] if ml_weather else 0.0,
                "ml_weather": ml_weather or {},
                "ml_score_breakdown": ml_score_card["breakdown"] if ml_score_card else {},
                "score_breakdown": score_card["breakdown"],
                "weights": score_card["weights"],
                "reason": reason,
                "reason_summary": generate_summary(reason),
                "history_baseline": history_baseline or {},
            }
        )
    scored_rows.sort(key=lambda item: item["score_total"], reverse=True)
    for index, row in enumerate(scored_rows, start=1):
        row["rank"] = index
    return scored_rows


def build_ml_prediction_highlights(ranking: list[dict], limit: int = 3) -> list[dict]:
    candidates = [row for row in ranking if row.get("ml_score") is not None]
    candidates.sort(key=lambda item: item["ml_score"], reverse=True)
    return candidates[:limit]


def build_homepage_context(repository, selected_date: str, preferences: dict) -> dict:
    forecast_df = repository.get_forecast_for_date(selected_date)
    history_df = repository.get_history_monthly()
    history_daily_df = repository.get_history_daily()
    aqi_available = repository.aqi_available()
    ranking = build_ranked_records(
        forecast_df,
        history_df,
        preferences,
        aqi_available=aqi_available,
        history_daily_df=history_daily_df,
    )
    chart_data = {
        "cities": [row["city_name"] for row in ranking],
        "scores": [row["score_total"] for row in ranking],
    }
    return {
        "ranking": ranking,
        "chart_data": chart_data,
        "ml_predictions": build_ml_prediction_highlights(ranking),
        "weights_preview": build_weights(preferences, aqi_available=aqi_available),
        "aqi_available": aqi_available,
        "model_summary": build_model_summary(history_df, history_daily_df),
    }


def build_city_detail_context(repository, city_slug: str, selected_date: str, preferences: dict) -> dict:
    city_forecast = repository.get_city_forecast(city_slug)
    history_df = repository.get_history_monthly()
    history_daily_df = repository.get_history_daily()
    aqi_available = repository.aqi_available()
    scored_series = build_ranked_records(
        city_forecast,
        history_df,
        preferences,
        aqi_available=aqi_available,
        history_daily_df=history_daily_df,
    )
    selected_row = next((row for row in scored_series if row["date"] == selected_date), None)
    chronological_series = sorted(scored_series, key=lambda row: row["date"])
    history_series = history_df[history_df["city_slug"] == city_slug].sort_values("month_key").to_dict("records")
    trend_chart = {
        "dates": [row["date"] for row in chronological_series],
        "scores": [row["score_total"] for row in chronological_series],
        "temps": [row["avg_temp"] for row in chronological_series],
    }
    ml_weather_chart = {
        "dates": [row["date"] for row in chronological_series],
        "api_temps": [row["avg_temp"] for row in chronological_series],
        "ml_temps": [row.get("ml_weather", {}).get("avg_temp") for row in chronological_series],
        "api_scores": [row.get("rule_score") for row in chronological_series],
        "ml_scores": [row.get("ml_score") for row in chronological_series],
        "rain_probabilities": [
            round(float(row.get("ml_weather", {}).get("rain_probability", 0.0)) * 100, 1)
            for row in chronological_series
        ],
    }
    breakdown_chart = {
        "labels": [label_map[dimension] for dimension in selected_row["score_breakdown"].keys()] if selected_row else [],
        "values": [item["score"] for item in selected_row["score_breakdown"].values()] if selected_row else [],
    }
    history_scores = [
        round(
            item["comfortable_days_ratio"] * 55
            + (1 - item["rainy_ratio"]) * 25
            + max(0, (1 - min(item["temp_std"], 12) / 12)) * 20,
            1,
        )
        for item in history_series
    ]
    history_smoothed_scores = (
        pd.Series(history_scores).rolling(window=3, min_periods=1, center=True).mean().round(1).tolist()
        if history_scores
        else []
    )
    history_chart = {
        "months": [item["month_key"] for item in history_series],
        "history_scores": history_scores,
        "history_smoothed_scores": history_smoothed_scores,
    }
    return {
        "selected": selected_row,
        "series": scored_series,
        "history_series": history_series,
        "trend_chart": trend_chart,
        "breakdown_chart": breakdown_chart,
        "ml_weather_chart": ml_weather_chart,
        "history_chart": history_chart,
        "aqi_available": aqi_available,
        "model_summary": build_model_summary(history_df, history_daily_df),
    }
