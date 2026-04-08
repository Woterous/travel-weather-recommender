from __future__ import annotations

import pandas as pd

from service.history_analysis import build_history_baseline_lookup
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
) -> list[dict]:
    if forecast_df.empty:
        return []
    baseline_lookup = build_history_baseline_lookup(history_df)
    scored_rows = []
    for row in forecast_df.to_dict("records"):
        history_baseline = baseline_lookup.get((row["city_slug"], _month_from_date(row["date"])))
        score_card = score_record(row, history_baseline, preferences, aqi_available=aqi_available)
        reason = generate_reason(row, score_card["breakdown"], preferences, history_baseline)
        scored_rows.append(
            {
                **row,
                "score_total": score_card["total"],
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


def build_homepage_context(repository, selected_date: str, preferences: dict) -> dict:
    forecast_df = repository.get_forecast_for_date(selected_date)
    history_df = repository.get_history_monthly()
    aqi_available = repository.aqi_available()
    ranking = build_ranked_records(forecast_df, history_df, preferences, aqi_available=aqi_available)
    chart_data = {
        "cities": [row["city_name"] for row in ranking],
        "scores": [row["score_total"] for row in ranking],
    }
    return {
        "ranking": ranking,
        "chart_data": chart_data,
        "weights_preview": build_weights(preferences, aqi_available=aqi_available),
        "aqi_available": aqi_available,
    }


def build_city_detail_context(repository, city_slug: str, selected_date: str, preferences: dict) -> dict:
    city_forecast = repository.get_city_forecast(city_slug)
    history_df = repository.get_history_monthly()
    aqi_available = repository.aqi_available()
    scored_series = build_ranked_records(city_forecast, history_df, preferences, aqi_available=aqi_available)
    selected_row = next((row for row in scored_series if row["date"] == selected_date), None)
    history_series = history_df[history_df["city_slug"] == city_slug].sort_values("month_key").to_dict("records")
    trend_chart = {
        "dates": [row["date"] for row in scored_series],
        "scores": [row["score_total"] for row in scored_series],
        "temps": [row["avg_temp"] for row in scored_series],
    }
    breakdown_chart = {
        "labels": [label_map[dimension] for dimension in selected_row["score_breakdown"].keys()] if selected_row else [],
        "values": [item["score"] for item in selected_row["score_breakdown"].values()] if selected_row else [],
    }
    history_chart = {
        "months": [item["month_key"] for item in history_series],
        "history_scores": [
            round(
                item["comfortable_days_ratio"] * 55
                + (1 - item["rainy_ratio"]) * 25
                + max(0, (1 - min(item["temp_std"], 12) / 12)) * 20,
                1,
            )
            for item in history_series
        ],
    }
    return {
        "selected": selected_row,
        "series": scored_series,
        "history_series": history_series,
        "trend_chart": trend_chart,
        "breakdown_chart": breakdown_chart,
        "history_chart": history_chart,
        "aqi_available": aqi_available,
    }
