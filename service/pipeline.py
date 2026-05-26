from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from config.cities import CityConfig
from config.sources import default_history_range
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
from service.database import WeatherRepository, delete_city_dataframe, log_refresh, write_city_dataframe, write_dataframe


BASE_DIR = Path(__file__).resolve().parents[1]
RAW_FORECAST_DIR = BASE_DIR / "data" / "raw" / "forecast"
RAW_HISTORY_DIR = BASE_DIR / "data" / "raw" / "history"
RAW_AIR_QUALITY_DIR = BASE_DIR / "data" / "raw" / "air_quality"


def _friendly_fetch_error(data_name: str, city_name: str, exc: Exception) -> str:
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    error_text = str(exc)
    if status_code == 429 or "429" in error_text or "Too Many Requests" in error_text:
        return f"{data_name}暂时不可用：{city_name} 请求过于频繁，本次未更新，请稍后重试。"
    if status_code in {502, 503, 504} or any(code in error_text for code in ["502", "503", "504", "Bad Gateway", "Gateway Time-out"]):
        return f"{data_name}暂时不可用：{city_name} 上游天气服务暂时不可用，本次未更新，请稍后重试。"
    return f"{data_name}暂时不可用：{city_name} 本次未更新，请稍后重试。"


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _emit_progress(progress_callback, **payload) -> None:
    if progress_callback:
        progress_callback(payload)


def _history_cache_is_current(repository: WeatherRepository, city_slug: str) -> bool:
    _start_date, end_date = default_history_range()
    coverage = repository.get_history_daily_coverage(city_slug)
    return coverage["row_count"] > 0 and str(coverage["end_date"] or "") >= end_date.isoformat()


def _forecast_cache_is_current(repository: WeatherRepository, city_slug: str, today: str | None = None) -> bool:
    return repository.forecast_cache_is_current(city_slug, today or date.today().isoformat())


def _aqi_cache_is_current(repository: WeatherRepository, city_slug: str, today: str | None = None) -> bool:
    return repository.aqi_cache_is_current(city_slug, today or date.today().isoformat())


def _refresh_city_list(repository: WeatherRepository) -> list[CityConfig]:
    cities = []
    seen_slugs = set()
    for item in repository.get_added_cities():
        slug = str(item.get("slug") or "").strip()
        if not slug or slug in seen_slugs:
            continue
        try:
            latitude = float(item["latitude"])
            longitude = float(item["longitude"])
        except (TypeError, ValueError):
            continue
        cities.append(
            CityConfig(
                slug=slug,
                name=str(item.get("name") or slug),
                pinyin=str(item.get("pinyin") or slug),
                latitude=latitude,
                longitude=longitude,
            )
        )
        seen_slugs.add(slug)
    return cities


def refresh_all_data(progress_callback=None) -> dict:     ##开始刷新数据
    crawl_time = to_iso_timestamp()     ##生成一次抓取时间 crawl_time
    client = HttpClient()
    page_payloads = {}
    api_payloads = {}
    air_quality_payloads = {}
    history_payloads = {}
    errors = []
    warnings = []
    skipped_history_cities = []
    skipped_forecast_cities = []
    skipped_aqi_cities = []
    repository = WeatherRepository()
    repository.prune_data_for_removed_cities()
    refresh_cities = _refresh_city_list(repository)
    total_steps = len(refresh_cities) * 4 + 5
    step = 0

    _emit_progress(
        progress_callback,
        status="running",
        step=step,
        total=total_steps,
        stage="准备刷新",
        message="正在初始化 HTTP 客户端和本次抓取时间。",
        next_step=f"下一步：抓取 {refresh_cities[0].name} 的未来天气网页。" if refresh_cities else "下一步：清洗本地数据。",
    )

    for city in refresh_cities:     ##遍历默认城市和用户添加城市，对每个城市分别抓三类数据
        forecast_reused = _forecast_cache_is_current(repository, city.slug)
        aqi_reused = _aqi_cache_is_current(repository, city.slug)

        _emit_progress(
            progress_callback,
            status="running",
            step=step + 1,
            total=total_steps,
            stage="未来天气网页",
            message=(
                f"{city.name} 今日未来天气缓存仍有效，本次跳过网页抓取。"
                if forecast_reused
                else f"正在抓取 {city.name} 的 7 日天气网页数据。"
            ),
            next_step=f"下一步：处理 {city.name} 的 Open-Meteo 未来天气 API。",
        )
        if not forecast_reused:
            try:        ##未来天气页面数据
                page_payload = fetch_forecast_page(city, client=client)
                page_payloads[city.slug] = page_payload
                suffix = crawl_time.replace(":", "-")
                _save_json(RAW_FORECAST_DIR / f"{city.slug}_page_{suffix}.json", page_payload)
            except Exception as exc:  # pragma: no cover
                warnings.append(f"{city.name} 网页天气源暂时不可用，已使用 Open-Meteo API 兜底。")

        step += 1
        page_message = (
            f"{city.name} 今日未来天气缓存仍有效。"
            if forecast_reused
            else f"{city.name} 天气网页抓取完成，已保存原始 JSON。"
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
            message=(
                f"{city.name} 今日未来天气缓存仍有效，本次不重复请求 API。"
                if forecast_reused
                else f"正在抓取 {city.name} 的温度、降水、风速等 API 数据。"
            ),
            next_step=f"下一步：处理 {city.name} 的 AQI 空气质量数据。",
        )
        if not forecast_reused:
            try:        ##未来天气 API 数据
                api_payload = fetch_forecast_api(city, client=client)
                api_payloads[city.slug] = api_payload
                suffix = crawl_time.replace(":", "-")
                _save_json(RAW_FORECAST_DIR / f"{city.slug}_api_{suffix}.json", api_payload)
            except Exception as exc:  # pragma: no cover
                message = _friendly_fetch_error("未来天气补充数据", city.name, exc)
                if city.slug in page_payloads:
                    warnings.append(f"{message} 已保留网页天气数据。")
                else:
                    errors.append(message)
        else:
            skipped_forecast_cities.append(city.name)

        step += 1
        _emit_progress(
            progress_callback,
            status="running",
            step=step,
            total=total_steps,
            stage="未来天气 API",
            message=f"{city.name} 未来天气 API 处理完成。" if not forecast_reused else f"{city.name} 未来天气已复用本地缓存。",
            next_step=f"下一步：抓取 {city.name} 的 AQI 空气质量。",
        )

        aqi_can_update = (not forecast_reused) and (city.slug in page_payloads or city.slug in api_payloads)
        _emit_progress(
            progress_callback,
            status="running",
            step=step + 1,
            total=total_steps,
            stage="AQI 空气质量",
            message=(
                f"{city.name} 今日 AQI 缓存仍有效，本次不重复请求 API。"
                if aqi_reused
                else f"{city.name} 暂无可合并的未来天气基础数据，本次跳过 AQI 请求。"
                if not aqi_can_update
                else f"正在抓取 {city.name} 的 AQI、PM2.5、PM10 等空气质量数据。"
            ),
            next_step=f"下一步：抓取 {city.name} 的历史天气归档。",
        )
        if not aqi_reused and aqi_can_update:
            try:
                air_quality_payload = fetch_air_quality_api(city, client=client)
                air_quality_payloads[city.slug] = air_quality_payload
                suffix = crawl_time.replace(":", "-")
                _save_json(RAW_AIR_QUALITY_DIR / f"{city.slug}_{suffix}.json", air_quality_payload)
            except Exception as exc:  # pragma: no cover
                errors.append(_friendly_fetch_error("AQI 数据", city.name, exc))
        elif aqi_reused:
            skipped_aqi_cities.append(city.name)

        step += 1
        _emit_progress(
            progress_callback,
            status="running",
            step=step,
            total=total_steps,
            stage="AQI 空气质量",
            message=(
                f"{city.name} AQI 已复用本地缓存。"
                if aqi_reused
                else f"{city.name} AQI 数据处理完成。"
                if aqi_can_update
                else f"{city.name} AQI 本次未请求，等待未来天气数据可用后再合并。"
            ),
            next_step=f"下一步：抓取 {city.name} 的历史天气。",
        )

        if _history_cache_is_current(repository, city.slug):
            skipped_history_cities.append(city.name)
            _emit_progress(
                progress_callback,
                status="running",
                step=step + 1,
                total=total_steps,
                stage="历史天气",
                message=f"{city.name} 历史日数据已覆盖到上个月，本次复用本地缓存。",
                next_step="下一步：继续处理后续城市，或进入数据清洗。",
            )
        else:
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
        next_city_index = refresh_cities.index(city) + 1
        next_step = (
            f"下一步：抓取 {refresh_cities[next_city_index].name} 的未来天气网页。"
            if next_city_index < len(refresh_cities)
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
    refreshed_forecast_slugs = set()
    if not forecast_df.empty:
        for city_slug in forecast_df["city_slug"].dropna().unique():
            refreshed_forecast_slugs.add(city_slug)
            write_city_dataframe(forecast_df[forecast_df["city_slug"] == city_slug], "forecast_daily", city_slug)
    for city in refresh_cities:
        if city.slug in refreshed_forecast_slugs or _forecast_cache_is_current(repository, city.slug):
            continue
        delete_city_dataframe("forecast_daily", city.slug)
    if not history_df.empty:
        for city_slug in history_df["city_slug"].dropna().unique():
            write_city_dataframe(history_df[history_df["city_slug"] == city_slug], "history_monthly", city_slug)
    if not history_daily_df.empty:
        for city_slug in history_daily_df["city_slug"].dropna().unique():
            write_city_dataframe(history_daily_df[history_daily_df["city_slug"] == city_slug], "history_daily", city_slug)

    total_forecast_df = repository.get_forecast_daily()
    total_history_df = repository.get_history_monthly()
    total_history_daily_df = repository.get_history_daily()
    save_processed_artifacts(total_forecast_df, total_history_df, total_history_daily_df)   ##把整理后的结果保存成 CSV 文件

    step += 1
    aqi_rows = int(total_forecast_df["aqi"].notna().sum()) if not total_forecast_df.empty and "aqi" in total_forecast_df else 0
    status = "success" if not errors else "partial"
    message_parts = [
        f"未来天气 {len(total_forecast_df)} 条，AQI {aqi_rows} 条，历史月度统计 {len(total_history_df)} 条，历史日样本 {len(total_history_daily_df)} 条。"
    ]
    if skipped_forecast_cities:
        message_parts.append(f"未来天气已复用今日缓存 {len(skipped_forecast_cities)} 个城市。")
    if skipped_aqi_cities:
        message_parts.append(f"AQI 已复用今日缓存 {len(skipped_aqi_cities)} 个城市。")
    if skipped_history_cities:
        message_parts.append(f"历史数据已复用本地缓存 {len(skipped_history_cities)} 个城市。")
    if warnings:
        message_parts.append(" ".join(warnings))
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
        "forecast_rows": len(total_forecast_df),
        "aqi_rows": aqi_rows,
        "history_rows": len(total_history_df),
        "history_daily_rows": len(total_history_daily_df),
        "errors": errors,
        "warnings": warnings,
        "message": message,
    }


def refresh_city_data(city) -> dict:
    crawl_time = to_iso_timestamp()
    client = HttpClient()
    page_payloads = {}
    api_payloads = {}
    air_quality_payloads = {}
    history_payloads = {}
    errors = []
    repository = WeatherRepository()
    today = date.today().isoformat()
    forecast_reused = _forecast_cache_is_current(repository, city.slug, today)
    aqi_reused = _aqi_cache_is_current(repository, city.slug, today)

    if not forecast_reused:
        try:
            page_payload = fetch_forecast_page(city, client=client)
            page_payloads[city.slug] = page_payload
            suffix = crawl_time.replace(":", "-")
            _save_json(RAW_FORECAST_DIR / f"{city.slug}_page_{suffix}.json", page_payload)
        except Exception:
            pass

        try:
            api_payload = fetch_forecast_api(city, client=client)
            api_payloads[city.slug] = api_payload
            suffix = crawl_time.replace(":", "-")
            _save_json(RAW_FORECAST_DIR / f"{city.slug}_api_{suffix}.json", api_payload)
        except Exception as exc:  # pragma: no cover
            message = _friendly_fetch_error("未来天气 API 数据", city.name, exc)
            if city.slug not in page_payloads:
                errors.append(message)

    forecast_available_for_aqi = (not forecast_reused) and (city.slug in page_payloads or city.slug in api_payloads)
    if not aqi_reused and forecast_available_for_aqi:
        try:
            air_quality_payload = fetch_air_quality_api(city, client=client)
            air_quality_payloads[city.slug] = air_quality_payload
            suffix = crawl_time.replace(":", "-")
            _save_json(RAW_AIR_QUALITY_DIR / f"{city.slug}_{suffix}.json", air_quality_payload)
        except Exception as exc:  # pragma: no cover
            errors.append(_friendly_fetch_error("AQI 数据", city.name, exc))

    history_reused = _history_cache_is_current(repository, city.slug)
    if not history_reused:
        try:
            history_payload = fetch_history_daily(city, client=client)
            history_payloads[city.slug] = history_payload
            _save_json(RAW_HISTORY_DIR / f"{city.slug}_{crawl_time.replace(':', '-')}.json", history_payload)
        except Exception as exc:  # pragma: no cover
            errors.append(_friendly_fetch_error("历史数据", city.name, exc))

    forecast_df = build_forecast_dataset(page_payloads, api_payloads, crawl_time, air_quality_payloads)
    history_df = build_history_monthly_dataset(history_payloads, crawl_time)
    history_daily_df = build_history_daily_dataset(history_payloads, crawl_time)

    if not forecast_df.empty:
        write_city_dataframe(forecast_df, "forecast_daily", city.slug)
    elif not forecast_reused:
        delete_city_dataframe("forecast_daily", city.slug)
    if not history_df.empty:
        write_city_dataframe(history_df, "history_monthly", city.slug)
    if not history_daily_df.empty:
        write_city_dataframe(history_daily_df, "history_daily", city.slug)

    total_city_forecast_df = repository.get_city_forecast(city.slug)
    total_city_history_df = repository.get_history_monthly(city.slug)
    total_city_history_daily_df = repository.get_history_daily(city.slug)
    aqi_rows = int(forecast_df["aqi"].notna().sum()) if not forecast_df.empty and "aqi" in forecast_df else 0
    if forecast_reused:
        aqi_rows = int(total_city_forecast_df["aqi"].notna().sum()) if not total_city_forecast_df.empty and "aqi" in total_city_forecast_df else 0
    status = "success" if not errors else "partial"
    message = (
        f"{city.name} 未来天气 {len(total_city_forecast_df)} 条，AQI {aqi_rows} 条，历史月度统计 {len(total_city_history_df)} 条，历史日样本 {len(total_city_history_daily_df)} 条。"
        + (" 未来天气已复用今日缓存。" if forecast_reused else "")
        + (" AQI 已复用今日缓存。" if aqi_reused else "")
        + (" 历史数据已复用本地缓存。" if history_reused else "")
        + ("; " + " | ".join(errors) if errors else "")
    )
    log_refresh(crawl_time, status, message)
    return {
        "status": status,
        "crawl_time": crawl_time,
        "forecast_rows": len(total_city_forecast_df),
        "aqi_rows": aqi_rows,
        "history_rows": len(total_city_history_df),
        "history_daily_rows": len(total_city_history_daily_df),
        "errors": errors,
        "message": message,
    }


def preview_city_forecast(city) -> dict:
    crawl_time = to_iso_timestamp()
    errors = []
    api_payloads = {}
    try:
        api_payloads[city.slug] = fetch_forecast_api(city, client=HttpClient())
    except Exception as exc:  # pragma: no cover
        errors.append(_friendly_fetch_error("当前天气预览", city.name, exc))

    forecast_df = build_forecast_dataset({}, api_payloads, crawl_time)
    if forecast_df.empty:
        return {"city": city, "forecast": None, "errors": errors}
    row = forecast_df.sort_values("date").iloc[0].to_dict()
    return {"city": city, "forecast": row, "errors": errors}
