from __future__ import annotations

import json
from pathlib import Path

from config.cities import CITIES
from crawler.air_quality_crawler import fetch_air_quality_api
from crawler.fetcher import HttpClient
from crawler.forecast_crawler import fetch_forecast_api, fetch_forecast_page
from crawler.history_crawler import fetch_history_daily
from crawler.parser_utils import to_iso_timestamp
from service.clean_data import (
    build_forecast_dataset,
    build_history_daily_dataset,
    build_history_monthly_dataset,
    save_processed_artifacts,
) ##引用import数据清洗函数
from service.database import log_refresh, write_city_dataframe, write_dataframe


BASE_DIR = Path(__file__).resolve().parents[1]
RAW_FORECAST_DIR = BASE_DIR / "data" / "raw" / "forecast"
RAW_HISTORY_DIR = BASE_DIR / "data" / "raw" / "history"
RAW_AIR_QUALITY_DIR = BASE_DIR / "data" / "raw" / "air_quality"


def _friendly_fetch_error(data_name: str, city_name: str, exc: Exception) -> str:
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    error_text = str(exc)
    if status_code == 429 or "429" in error_text or "Too Many Requests" in error_text:
        return f"{data_name}暂时不可用：{city_name} 请求过于频繁，本次未更新，请稍后重试。"
    return f"{data_name}暂时不可用：{city_name} 本次未更新，请稍后重试。"


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _emit_progress(progress_callback, **payload) -> None:
    if progress_callback:
        progress_callback(payload)


def refresh_all_data(progress_callback=None) -> dict:     ##开始刷新数据
    crawl_time = to_iso_timestamp()     ##生成一次抓取时间 crawl_time
    client = HttpClient()
    page_payloads = {}
    api_payloads = {}
    air_quality_payloads = {}
    history_payloads = {}
    errors = []
    warnings = []
    total_steps = len(CITIES) * 4 + 5
    step = 0

    _emit_progress(
        progress_callback,
        status="running",
        step=step,
        total=total_steps,
        stage="准备刷新",
        message="正在初始化 HTTP 客户端和本次抓取时间。",
        next_step=f"下一步：抓取 {CITIES[0].name} 的未来天气网页。",
    )

    for city in CITIES:     ##遍历配置里的所有城市，对每个城市分别抓三类数据
        _emit_progress(
            progress_callback,
            status="running",
            step=step + 1,
            total=total_steps,
            stage="未来天气网页",
            message=f"正在抓取 {city.name} 的 7 日天气网页数据。",
            next_step=f"下一步：抓取 {city.name} 的 Open-Meteo 未来天气 API。",
        )
        try:        ##未来天气页面数据
            page_payload = fetch_forecast_page(city, client=client)
            page_payloads[city.slug] = page_payload
            suffix = crawl_time.replace(":", "-")
            _save_json(RAW_FORECAST_DIR / f"{city.slug}_page_{suffix}.json", page_payload)
        except Exception as exc:  # pragma: no cover
            warnings.append(f"{city.name} 网页天气源暂时不可用，已使用 Open-Meteo API 兜底。")

        step += 1
        page_message = (
            f"{city.name} 天气网页抓取完成，已保存原始 JSON。"
            if city.slug in page_payloads
            else f"{city.name} 网页天气源不可用，继续使用 API 兜底。"
        )
        _emit_progress(
            progress_callback,
            status="running",
            step=step,
            total=total_steps,
            stage="未来天气网页",
            message=page_message,
            next_step=f"下一步：抓取 {city.name} 的未来天气 API 补充数据。",
        )

        _emit_progress(
            progress_callback,
            status="running",
            step=step + 1,
            total=total_steps,
            stage="未来天气 API",
            message=f"正在抓取 {city.name} 的温度、降水、风速等 API 数据。",
            next_step=f"下一步：抓取 {city.name} 的 AQI 空气质量数据。",
        )
        try:        ##未来天气 API 数据
            api_payload = fetch_forecast_api(city, client=client)
            api_payloads[city.slug] = api_payload
            suffix = crawl_time.replace(":", "-")
            _save_json(RAW_FORECAST_DIR / f"{city.slug}_api_{suffix}.json", api_payload)
        except Exception as exc:  # pragma: no cover
            errors.append(_friendly_fetch_error("未来天气补充数据", city.name, exc))

        step += 1
        _emit_progress(
            progress_callback,
            status="running",
            step=step,
            total=total_steps,
            stage="未来天气 API",
            message=f"{city.name} 未来天气 API 处理完成。",
            next_step=f"下一步：抓取 {city.name} 的 AQI 空气质量。",
        )

        _emit_progress(
            progress_callback,
            status="running",
            step=step + 1,
            total=total_steps,
            stage="AQI 空气质量",
            message=f"正在抓取 {city.name} 的 AQI、PM2.5、PM10 等空气质量数据。",
            next_step=f"下一步：抓取 {city.name} 的历史天气归档。",
        )
        try:
            air_quality_payload = fetch_air_quality_api(city, client=client)
            air_quality_payloads[city.slug] = air_quality_payload
            suffix = crawl_time.replace(":", "-")
            _save_json(RAW_AIR_QUALITY_DIR / f"{city.slug}_{suffix}.json", air_quality_payload)
        except Exception as exc:  # pragma: no cover
            errors.append(_friendly_fetch_error("AQI 数据", city.name, exc))

        step += 1
        _emit_progress(
            progress_callback,
            status="running",
            step=step,
            total=total_steps,
            stage="AQI 空气质量",
            message=f"{city.name} AQI 数据处理完成。",
            next_step=f"下一步：抓取 {city.name} 的历史天气。",
        )

        _emit_progress(
            progress_callback,
            status="running",
            step=step + 1,
            total=total_steps,
            stage="历史天气",
            message=f"正在抓取 {city.name} 的历史日天气，用于月度统计和机器学习预测。",
            next_step="下一步：继续处理后续城市，或进入数据清洗。",
        )
        try:        ##历史天气数据
            history_payload = fetch_history_daily(city, client=client)
            history_payloads[city.slug] = history_payload
            _save_json(RAW_HISTORY_DIR / f"{city.slug}_{crawl_time.replace(':', '-')}.json", history_payload)
        except Exception as exc:  # pragma: no cover
            errors.append(_friendly_fetch_error("历史数据", city.name, exc))

        step += 1
        next_city_index = CITIES.index(city) + 1
        next_step = (
            f"下一步：抓取 {CITIES[next_city_index].name} 的未来天气网页。"
            if next_city_index < len(CITIES)
            else "下一步：清洗未来天气、AQI 和历史天气数据。"
        )
        _emit_progress(
            progress_callback,
            status="running",
            step=step,
            total=total_steps,
            stage="历史天气",
            message=f"{city.name} 历史天气处理完成。",
            next_step=next_step,
        )

    step += 1
    _emit_progress(
        progress_callback,
        status="running",
        step=step,
        total=total_steps,
        stage="数据清洗",
        message="正在合并未来天气、AQI 和历史月度统计数据。",
        next_step="下一步：生成处理后的 CSV 文件。",
    )
    forecast_df = build_forecast_dataset(page_payloads, api_payloads, crawl_time, air_quality_payloads)   ##把抓到的未来天气原始数据整理成表
    history_df = build_history_monthly_dataset(history_payloads, crawl_time)    ##把抓到的历史日数据整理成“历史月度统计表”
    history_daily_df = build_history_daily_dataset(history_payloads, crawl_time)

    step += 1
    _emit_progress(
        progress_callback,
        status="running",
        step=step,
        total=total_steps,
        stage="生成 CSV",
        message="正在保存 forecast_daily.csv、history_monthly.csv 和 history_daily.csv。",
        next_step="下一步：写入 SQLite 数据库。",
    )
    save_processed_artifacts(forecast_df, history_df, history_daily_df)   ##把整理后的结果保存成 CSV 文件

    step += 1
    _emit_progress(
        progress_callback,
        status="running",
        step=step,
        total=total_steps,
        stage="写入数据库",
        message="正在将刷新结果写入 SQLite 表。",
        next_step="下一步：记录刷新日志并重新计算页面推荐。",
    )
    if not forecast_df.empty:
        write_dataframe(forecast_df, "forecast_daily", replace=True)
    if not history_df.empty:
        write_dataframe(history_df, "history_monthly", replace=True)
    if not history_daily_df.empty:
        write_dataframe(history_daily_df, "history_daily", replace=True)

    step += 1
    aqi_rows = int(forecast_df["aqi"].notna().sum()) if not forecast_df.empty and "aqi" in forecast_df else 0
    status = "success" if not errors else "partial"
    message_parts = [
        f"未来天气 {len(forecast_df)} 条，AQI {aqi_rows} 条，历史月度统计 {len(history_df)} 条，历史日样本 {len(history_daily_df)} 条。"
    ]
    if warnings:
        message_parts.append("网页天气源部分不可用，已使用 Open-Meteo API 兜底。")
    if errors:
        message_parts.append(" | ".join(errors))
    message = " ".join(message_parts)
    log_refresh(crawl_time, status, message)
    _emit_progress(
        progress_callback,
        status="running",
        step=step,
        total=total_steps,
        stage="刷新日志",
        message="刷新日志已记录，正在准备返回首页。",
        next_step="下一步：页面将加载最新排行榜。",
    )
    step += 1
    _emit_progress(
        progress_callback,
        status="running",
        step=total_steps,
        total=total_steps,
        stage="刷新完成",
        message=message,
        next_step="刷新完成，即将重新加载页面。",
    )
    return {
        "status": status,
        "crawl_time": crawl_time,
        "forecast_rows": len(forecast_df),
        "aqi_rows": aqi_rows,
        "history_rows": len(history_df),
        "history_daily_rows": len(history_daily_df),
        "errors": errors,
        "warnings": warnings,
        "message": message,
    }


def refresh_city_data(city) -> dict:
    crawl_time = to_iso_timestamp()
    client = HttpClient()
    api_payloads = {}
    air_quality_payloads = {}
    history_payloads = {}
    errors = []

    try:
        api_payload = fetch_forecast_api(city, client=client)
        api_payloads[city.slug] = api_payload
        suffix = crawl_time.replace(":", "-")
        _save_json(RAW_FORECAST_DIR / f"{city.slug}_api_{suffix}.json", api_payload)
    except Exception as exc:  # pragma: no cover
        errors.append(_friendly_fetch_error("未来天气 API 数据", city.name, exc))

    try:
        air_quality_payload = fetch_air_quality_api(city, client=client)
        air_quality_payloads[city.slug] = air_quality_payload
        suffix = crawl_time.replace(":", "-")
        _save_json(RAW_AIR_QUALITY_DIR / f"{city.slug}_{suffix}.json", air_quality_payload)
    except Exception as exc:  # pragma: no cover
        errors.append(_friendly_fetch_error("AQI 数据", city.name, exc))

    try:
        history_payload = fetch_history_daily(city, client=client)
        history_payloads[city.slug] = history_payload
        _save_json(RAW_HISTORY_DIR / f"{city.slug}_{crawl_time.replace(':', '-')}.json", history_payload)
    except Exception as exc:  # pragma: no cover
        errors.append(_friendly_fetch_error("历史数据", city.name, exc))

    forecast_df = build_forecast_dataset({}, api_payloads, crawl_time, air_quality_payloads)
    history_df = build_history_monthly_dataset(history_payloads, crawl_time)
    history_daily_df = build_history_daily_dataset(history_payloads, crawl_time)

    if not forecast_df.empty:
        write_city_dataframe(forecast_df, "forecast_daily", city.slug)
    if not history_df.empty:
        write_city_dataframe(history_df, "history_monthly", city.slug)
    if not history_daily_df.empty:
        write_city_dataframe(history_daily_df, "history_daily", city.slug)

    aqi_rows = int(forecast_df["aqi"].notna().sum()) if not forecast_df.empty and "aqi" in forecast_df else 0
    status = "success" if not errors else "partial"
    message = (
        f"{city.name} 未来天气 {len(forecast_df)} 条，AQI {aqi_rows} 条，历史月度统计 {len(history_df)} 条，历史日样本 {len(history_daily_df)} 条。"
        + ("; " + " | ".join(errors) if errors else "")
    )
    log_refresh(crawl_time, status, message)
    return {
        "status": status,
        "crawl_time": crawl_time,
        "forecast_rows": len(forecast_df),
        "aqi_rows": aqi_rows,
        "history_rows": len(history_df),
        "history_daily_rows": len(history_daily_df),
        "errors": errors,
        "message": message,
    }
