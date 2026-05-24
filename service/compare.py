from __future__ import annotations

from service.history_analysis import get_city_history_series
from service.ranking import build_ranked_records, label_map


def build_compare_context(repository, city_a: str, city_b: str, selected_date: str, preferences: dict) -> dict:
    history_df = repository.get_history_monthly()
    history_daily_df = repository.get_history_daily()
    aqi_available = repository.aqi_available()
    forecast_a = repository.get_city_forecast(city_a)
    forecast_b = repository.get_city_forecast(city_b)
    scored_a = build_ranked_records(
        forecast_a,
        history_df,
        preferences,
        aqi_available=aqi_available,
        history_daily_df=history_daily_df,
    )
    scored_b = build_ranked_records(
        forecast_b,
        history_df,
        preferences,
        aqi_available=aqi_available,
        history_daily_df=history_daily_df,
    )
    row_a = next((row for row in scored_a if row["date"] == selected_date), None)
    row_b = next((row for row in scored_b if row["date"] == selected_date), None)

    if not row_a or not row_b:
        return {"row_a": None, "row_b": None, "aqi_available": aqi_available}

    compare_chart = {
        "labels": [label_map[key] for key in row_a["score_breakdown"].keys()],
        "city_a": [item["score"] for item in row_a["score_breakdown"].values()],
        "city_b": [item["score"] for item in row_b["score_breakdown"].values()],
    }
    history_a = get_city_history_series(history_df, city_a)
    history_b = get_city_history_series(history_df, city_b)
    history_chart = {
        "months": [item["month_key"] for item in history_a],
        "city_a": [item["history_score"] for item in history_a],
        "city_b": [item["history_score"] for item in history_b],
    }
    return {
        "row_a": row_a,
        "row_b": row_b,
        "compare_chart": compare_chart,
        "history_chart": history_chart,
        "aqi_available": aqi_available,
    }
