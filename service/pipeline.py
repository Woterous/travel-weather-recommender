from __future__ import annotations

import json
from pathlib import Path

from config.cities import CITIES
from crawler.fetcher import HttpClient
from crawler.forecast_crawler import fetch_forecast_api, fetch_forecast_page
from crawler.history_crawler import fetch_history_daily
from crawler.parser_utils import to_iso_timestamp
from service.clean_data import build_forecast_dataset, build_history_monthly_dataset, save_processed_artifacts
from service.database import log_refresh, write_dataframe


BASE_DIR = Path(__file__).resolve().parents[1]
RAW_FORECAST_DIR = BASE_DIR / "data" / "raw" / "forecast"
RAW_HISTORY_DIR = BASE_DIR / "data" / "raw" / "history"


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_all_data() -> dict:
    crawl_time = to_iso_timestamp()
    client = HttpClient()
    page_payloads = {}
    api_payloads = {}
    history_payloads = {}
    errors = []

    for city in CITIES:
        try:
            page_payload = fetch_forecast_page(city, client=client)
            page_payloads[city.slug] = page_payload
            suffix = crawl_time.replace(":", "-")
            _save_json(RAW_FORECAST_DIR / f"{city.slug}_page_{suffix}.json", page_payload)
        except Exception as exc:  # pragma: no cover
            errors.append(f"未来天气抓取失败: {city.name} -> {exc}")

        try:
            api_payload = fetch_forecast_api(city, client=client)
            api_payloads[city.slug] = api_payload
            suffix = crawl_time.replace(":", "-")
            _save_json(RAW_FORECAST_DIR / f"{city.slug}_api_{suffix}.json", api_payload)
        except Exception as exc:  # pragma: no cover
            errors.append(f"未来天气补充数据失败: {city.name} -> {exc}")

        try:
            history_payload = fetch_history_daily(city, client=client)
            history_payloads[city.slug] = history_payload
            _save_json(RAW_HISTORY_DIR / f"{city.slug}_{crawl_time.replace(':', '-')}.json", history_payload)
        except Exception as exc:  # pragma: no cover
            errors.append(f"历史数据抓取失败: {city.name} -> {exc}")

    forecast_df = build_forecast_dataset(page_payloads, api_payloads, crawl_time)
    history_df = build_history_monthly_dataset(history_payloads, crawl_time)
    save_processed_artifacts(forecast_df, history_df)

    if not forecast_df.empty:
        write_dataframe(forecast_df, "forecast_daily", replace=True)
    if not history_df.empty:
        write_dataframe(history_df, "history_monthly", replace=True)

    status = "success" if not errors else "partial"
    message = (
        f"未来天气 {len(forecast_df)} 条，历史月度统计 {len(history_df)} 条。"
        + ("; " + " | ".join(errors) if errors else "")
    )
    log_refresh(crawl_time, status, message)
    return {
        "status": status,
        "crawl_time": crawl_time,
        "forecast_rows": len(forecast_df),
        "history_rows": len(history_df),
        "errors": errors,
        "message": message,
    }
