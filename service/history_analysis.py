from __future__ import annotations

import pandas as pd


def build_history_baseline_lookup(history_df: pd.DataFrame) -> dict:
    if history_df.empty:
        return {}
    grouped = (
        history_df.groupby(["city_slug", "month_num"], as_index=False)
        .agg(
            avg_temp=("avg_temp", "mean"),
            rainy_ratio=("rainy_ratio", "mean"),
            comfortable_days_ratio=("comfortable_days_ratio", "mean"),
            temp_std=("temp_std", "mean"),
            avg_wind_speed_kmh=("avg_wind_speed_kmh", "mean"),
        )
    )
    return {
        (row["city_slug"], int(row["month_num"])): row.to_dict()
        for _index, row in grouped.iterrows()
    }


def score_history_monthly_row(row: dict) -> float:
    comfortable_component = float(row.get("comfortable_days_ratio", 0.0)) * 55
    rain_component = (1 - float(row.get("rainy_ratio", 0.0))) * 25
    temp_std = float(row.get("temp_std", 0.0))
    stability_component = max(0, (1 - min(temp_std, 12) / 12)) * 20
    return round(min(100, comfortable_component + rain_component + stability_component), 1)


def get_city_history_series(history_df: pd.DataFrame, city_slug: str) -> list[dict]:
    city_df = history_df[history_df["city_slug"] == city_slug].copy()
    if city_df.empty:
        return []
    city_df["history_score"] = city_df.apply(lambda row: score_history_monthly_row(row.to_dict()), axis=1)
    city_df = city_df.sort_values("month_key")
    return city_df.to_dict("records")


def get_history_ranking(history_df: pd.DataFrame, month_num: int, metric: str) -> list[dict]:
    if history_df.empty:
        return []
    filtered = history_df[history_df["month_num"] == month_num].copy()
    if filtered.empty:
        return []
    grouped = filtered.groupby(["city_slug", "city_name"], as_index=False).agg(
        avg_temp=("avg_temp", "mean"),
        rainy_ratio=("rainy_ratio", "mean"),
        comfortable_days_ratio=("comfortable_days_ratio", "mean"),
        temp_std=("temp_std", "mean"),
    )
    grouped["history_score"] = grouped.apply(lambda row: score_history_monthly_row(row.to_dict()), axis=1)

    metric_map = {
        "suitability": ("history_score", False),
        "rainy_ratio": ("rainy_ratio", True),
        "comfortable_ratio": ("comfortable_days_ratio", False),
        "temp_stability": ("temp_std", True),
    }
    sort_column, ascending = metric_map.get(metric, ("history_score", False))
    grouped = grouped.sort_values(sort_column, ascending=ascending).reset_index(drop=True)
    grouped["rank"] = grouped.index + 1
    return grouped.to_dict("records")


def month_num_options(history_df: pd.DataFrame) -> list[int]:
    if history_df.empty:
        return list(range(1, 13))
    return sorted({int(value) for value in history_df["month_num"].dropna().astype(int).tolist()})
