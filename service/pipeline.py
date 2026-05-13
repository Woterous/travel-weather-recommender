from __future__ import annotations

import json
from pathlib import Path

from config.cities import CITIES
from crawler.air_quality_crawler import fetch_air_quality_api
from crawler.fetcher import HttpClient
from crawler.forecast_crawler import fetch_forecast_api, fetch_forecast_page
from crawler.history_crawler import fetch_history_daily
from crawler.parser_utils import to_iso_timestamp
from service.clean_data import build_forecast_dataset, build_history_monthly_dataset, save_processed_artifacts ##引用import数据清洗函数
from service.database import log_refresh, write_dataframe


BASE_DIR = Path(__file__).resolve().parents[1]
RAW_FORECAST_DIR = BASE_DIR / "data" / "raw" / "forecast"
RAW_HISTORY_DIR = BASE_DIR / "data" / "raw" / "history"
RAW_AIR_QUALITY_DIR = BASE_DIR / "data" / "raw" / "air_quality"


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_all_data() -> dict:     ##开始刷新数据
    crawl_time = to_iso_timestamp()     ##生成一次抓取时间 crawl_time
    client = HttpClient()
    page_payloads = {}
    api_payloads = {}
    air_quality_payloads = {}
    history_payloads = {}
    errors = []

    for city in CITIES:     ##遍历配置里的所有城市，对每个城市分别抓三类数据
        try:        ##未来天气页面数据
            page_payload = fetch_forecast_page(city, client=client)
            page_payloads[city.slug] = page_payload
            suffix = crawl_time.replace(":", "-")
            _save_json(RAW_FORECAST_DIR / f"{city.slug}_page_{suffix}.json", page_payload)
        except Exception as exc:  # pragma: no cover
            errors.append(f"未来天气抓取失败: {city.name} -> {exc}")

        try:        ##未来天气 API 数据
            api_payload = fetch_forecast_api(city, client=client)
            api_payloads[city.slug] = api_payload
            suffix = crawl_time.replace(":", "-")
            _save_json(RAW_FORECAST_DIR / f"{city.slug}_api_{suffix}.json", api_payload)
        except Exception as exc:  # pragma: no cover
            errors.append(f"未来天气补充数据失败: {city.name} -> {exc}")

        try:
            air_quality_payload = fetch_air_quality_api(city, client=client)
            air_quality_payloads[city.slug] = air_quality_payload
            suffix = crawl_time.replace(":", "-")
            _save_json(RAW_AIR_QUALITY_DIR / f"{city.slug}_{suffix}.json", air_quality_payload)
        except Exception as exc:  # pragma: no cover
            errors.append(f"AQI 数据抓取失败: {city.name} -> {exc}")

        try:        ##历史天气数据
            history_payload = fetch_history_daily(city, client=client)
            history_payloads[city.slug] = history_payload
            _save_json(RAW_HISTORY_DIR / f"{city.slug}_{crawl_time.replace(':', '-')}.json", history_payload)
        except Exception as exc:  # pragma: no cover
            errors.append(f"历史数据抓取失败: {city.name} -> {exc}")

    forecast_df = build_forecast_dataset(page_payloads, api_payloads, crawl_time, air_quality_payloads)   ##把抓到的未来天气原始数据整理成表
    history_df = build_history_monthly_dataset(history_payloads, crawl_time)    ##把抓到的历史日数据整理成“历史月度统计表”
    save_processed_artifacts(forecast_df, history_df)   ##把整理后的结果保存成 CSV 文件

    if not forecast_df.empty:
        write_dataframe(forecast_df, "forecast_daily", replace=True)
    if not history_df.empty:
        write_dataframe(history_df, "history_monthly", replace=True)

    aqi_rows = int(forecast_df["aqi"].notna().sum()) if not forecast_df.empty and "aqi" in forecast_df else 0
    status = "success" if not errors else "partial"
    message = (
        f"未来天气 {len(forecast_df)} 条，AQI {aqi_rows} 条，历史月度统计 {len(history_df)} 条。"
        + ("; " + " | ".join(errors) if errors else "")
    )
    log_refresh(crawl_time, status, message)
    return {
        "status": status,
        "crawl_time": crawl_time,
        "forecast_rows": len(forecast_df),
        "aqi_rows": aqi_rows,
        "history_rows": len(history_df),
        "errors": errors,
        "message": message,
    }
