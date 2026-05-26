from __future__ import annotations

from pathlib import Path

import pandas as pd

from crawler.parser_utils import infer_rain_flag, normalize_weather_type


BASE_DIR = Path(__file__).resolve().parents[1]
PROCESSED_DIR = BASE_DIR / "data" / "processed"
UNIVERSAL_MILD_TEMP = 22.0


def _add_adaptive_comfort_flag(city_daily: pd.DataFrame) -> pd.DataFrame:
    city_daily = city_daily.copy()
    city_daily["month_num"] = city_daily["date"].dt.month
    monthly_avg = city_daily.groupby(["city_slug", "month_num"])["avg_temp"].transform("mean")
    monthly_std = city_daily.groupby(["city_slug", "month_num"])["avg_temp"].transform("std").fillna(0.0)

    adaptive_center = monthly_avg * 0.70 + UNIVERSAL_MILD_TEMP * 0.30
    half_width = (5.0 + monthly_std * 0.25).clip(lower=5.0, upper=7.0)
    lower_bound = adaptive_center - half_width
    upper_bound = adaptive_center + half_width

    city_daily["comfortable_flag"] = city_daily["avg_temp"].between(lower_bound, upper_bound, inclusive="both").astype(int)
    return city_daily


def build_forecast_dataset(
    page_payloads: dict,
    api_payloads: dict,
    crawl_time: str,
    air_quality_payloads: dict | None = None,
) -> pd.DataFrame:
    air_quality_payloads = air_quality_payloads or {}
    rows = []
    for city_slug in sorted(set(page_payloads) | set(api_payloads) | set(air_quality_payloads)):    ##合并数据，优先用页面数据，缺失时用 API 补充
        page_payload = page_payloads.get(city_slug, {})
        api_map = {record["date"]: record for record in api_payloads.get(city_slug, {}).get("records", [])}
        aqi_map = {record["date"]: record for record in air_quality_payloads.get(city_slug, {}).get("records", [])}
        page_dates = set()
        for record in page_payload.get("records", []):
            api_record = api_map.get(record["date"], {})
            aqi_record = aqi_map.get(record["date"], {})
            max_temp = record.get("max_temp") if record.get("max_temp") is not None else api_record.get("max_temp_api")
            min_temp = record.get("min_temp") if record.get("min_temp") is not None else api_record.get("min_temp_api")
            avg_temp = record.get("avg_temp")
            if avg_temp is None and max_temp is not None and min_temp is not None:
                avg_temp = round((max_temp + min_temp) / 2, 1)
            precipitation_mm = api_record.get("precipitation_mm", 0.0)
            rows.append(
                {
                    "city_slug": record["city_slug"],
                    "city_name": record["city_name"],
                    "date": record["date"],
                    "max_temp": max_temp,
                    "min_temp": min_temp,
                    "avg_temp": avg_temp,
                    "weather_type": normalize_weather_type(record.get("weather_detail")),   ##规范化天气类型
                    "weather_detail": record.get("weather_detail") or api_record.get("weather_detail_api"),
                    "wind_direction": record.get("wind_direction", ""),
                    "wind_speed_kmh": api_record.get("wind_speed_kmh"),
                    "wind_level": api_record.get("wind_level"),
                    "precipitation_mm": precipitation_mm,
                    "rain_flag": infer_rain_flag(record.get("weather_detail"), precipitation_mm),   ##判断是否下雨
                    "aqi": aqi_record.get("aqi"),
                    "source_type": "forecast",
                    "source_name": "tianqi.com + open-meteo forecast",
                    "crawl_time": crawl_time,
                }
            )
            page_dates.add(record["date"])

        for api_record in api_payloads.get(city_slug, {}).get("records", []):   ##统一字段类型、去重、排序
            if api_record["date"] in page_dates:
                continue
            aqi_record = aqi_map.get(api_record["date"], {})
            precipitation_mm = api_record.get("precipitation_mm", 0.0)
            rows.append(
                {
                    "city_slug": api_record["city_slug"],
                    "city_name": api_record["city_name"],
                    "date": api_record["date"],
                    "max_temp": api_record.get("max_temp_api"),
                    "min_temp": api_record.get("min_temp_api"),
                    "avg_temp": api_record.get("avg_temp_api"),
                    "weather_type": api_record.get("weather_type_api"),
                    "weather_detail": api_record.get("weather_detail_api"),
                    "wind_direction": "",
                    "wind_speed_kmh": api_record.get("wind_speed_kmh"),
                    "wind_level": api_record.get("wind_level"),
                    "precipitation_mm": precipitation_mm,
                    "rain_flag": infer_rain_flag(api_record.get("weather_detail_api"), precipitation_mm),
                    "aqi": aqi_record.get("aqi"),
                    "source_type": "forecast",
                    "source_name": "open-meteo forecast fallback",
                    "crawl_time": crawl_time,
                }
            )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    numeric_columns = ["max_temp", "min_temp", "avg_temp", "wind_speed_kmh", "precipitation_mm", "aqi"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["wind_level"] = pd.to_numeric(df["wind_level"], errors="coerce").astype("Int64")
    df["rain_flag"] = pd.to_numeric(df["rain_flag"], errors="coerce").fillna(0).astype(int)
    df = df.drop_duplicates(subset=["city_slug", "date"]).sort_values(["date", "city_slug"]).reset_index(drop=True)
    return df


def build_history_monthly_dataset(daily_payloads: dict, crawl_time: str) -> pd.DataFrame:
    monthly_frames = []
    for payload in daily_payloads.values():
        city_daily = pd.DataFrame(payload.get("records", []))
        if city_daily.empty:
            continue
        city_daily["date"] = pd.to_datetime(city_daily["date"])
        city_daily["precipitation_mm"] = pd.to_numeric(city_daily["precipitation_mm"], errors="coerce").fillna(0.0)
        city_daily["avg_temp"] = pd.to_numeric(city_daily["avg_temp"], errors="coerce")
        city_daily["max_temp"] = pd.to_numeric(city_daily["max_temp"], errors="coerce")
        city_daily["min_temp"] = pd.to_numeric(city_daily["min_temp"], errors="coerce")
        city_daily["wind_speed_kmh"] = pd.to_numeric(city_daily["wind_speed_kmh"], errors="coerce")
        city_daily["rain_flag"] = city_daily["precipitation_mm"].ge(0.1).astype(int)
        city_daily["month_key"] = city_daily["date"].dt.to_period("M").astype(str)
        city_daily = _add_adaptive_comfort_flag(city_daily)

        monthly = (
            city_daily.groupby(["city_slug", "city_name", "month_key", "month_num"], as_index=False)
            .agg(
                avg_max_temp=("max_temp", "mean"),
                avg_min_temp=("min_temp", "mean"),
                avg_temp=("avg_temp", "mean"),
                rainy_days=("rain_flag", "sum"),
                rainy_ratio=("rain_flag", "mean"),
                comfortable_days_ratio=("comfortable_flag", "mean"),
                temp_std=("avg_temp", "std"),
                avg_wind_speed_kmh=("wind_speed_kmh", "mean"),
            )
        )
        monthly["temp_std"] = monthly["temp_std"].fillna(0.0)
        monthly["source_type"] = "history_monthly"
        monthly["source_name"] = "open-meteo archive"
        monthly["crawl_time"] = crawl_time
        monthly_frames.append(monthly)

    if not monthly_frames:
        return pd.DataFrame()
    df = pd.concat(monthly_frames, ignore_index=True)
    df = df.drop_duplicates(subset=["city_slug", "month_key"]).sort_values(["city_slug", "month_key"])
    return df.reset_index(drop=True)


def build_history_daily_dataset(daily_payloads: dict, crawl_time: str) -> pd.DataFrame:
    frames = []
    for payload in daily_payloads.values():
        city_daily = pd.DataFrame(payload.get("records", []))
        if city_daily.empty:
            continue
        city_daily["date"] = pd.to_datetime(city_daily["date"])
        city_daily["max_temp"] = pd.to_numeric(city_daily["max_temp"], errors="coerce")
        city_daily["min_temp"] = pd.to_numeric(city_daily["min_temp"], errors="coerce")
        city_daily["avg_temp"] = pd.to_numeric(city_daily["avg_temp"], errors="coerce")
        if "weather_detail" not in city_daily:
            city_daily["weather_detail"] = ""
        city_daily["precipitation_mm"] = pd.to_numeric(city_daily["precipitation_mm"], errors="coerce").fillna(0.0)
        city_daily["wind_speed_kmh"] = pd.to_numeric(city_daily["wind_speed_kmh"], errors="coerce")
        city_daily["rain_flag"] = city_daily["precipitation_mm"].ge(0.1).astype(int)
        city_daily["month_num"] = city_daily["date"].dt.month
        city_daily["day_of_year"] = city_daily["date"].dt.dayofyear
        city_daily["date"] = city_daily["date"].dt.strftime("%Y-%m-%d")
        city_daily["source_type"] = "history_daily"
        city_daily["source_name"] = "open-meteo archive"
        city_daily["crawl_time"] = crawl_time
        columns = [
            "city_slug",
            "city_name",
            "date",
            "max_temp",
            "min_temp",
            "avg_temp",
            "weather_detail",
            "precipitation_mm",
            "rain_flag",
            "wind_speed_kmh",
            "month_num",
            "day_of_year",
            "source_type",
            "source_name",
            "crawl_time",
        ]
        frames.append(city_daily[columns])

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["city_slug", "date"]).sort_values(["city_slug", "date"])
    return df.reset_index(drop=True)


def save_processed_artifacts(
    forecast_df: pd.DataFrame,
    history_df: pd.DataFrame,
    history_daily_df: pd.DataFrame | None = None,
) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    if not forecast_df.empty:
        forecast_df.to_csv(PROCESSED_DIR / "forecast_daily.csv", index=False, encoding="utf-8-sig")
    if not history_df.empty:
        history_df.to_csv(PROCESSED_DIR / "history_monthly.csv", index=False, encoding="utf-8-sig")
    if history_daily_df is not None and not history_daily_df.empty:
        history_daily_df.to_csv(PROCESSED_DIR / "history_daily.csv", index=False, encoding="utf-8-sig")
