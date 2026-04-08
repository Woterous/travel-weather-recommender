from __future__ import annotations

from datetime import date

from bs4 import BeautifulSoup

from config.cities import CityConfig
from config.sources import build_forecast_api_url, build_forecast_page_url
from crawler.fetcher import HttpClient
from crawler.parser_utils import (
    cn_md_to_iso,
    compute_avg_temp,
    normalize_weather_type,
    safe_float,
    weather_code_to_cn,
    wind_speed_to_level,
)


def fetch_forecast_page(city: CityConfig, client: HttpClient | None = None) -> dict:
    http_client = client or HttpClient()
    url = build_forecast_page_url(city)
    html = http_client.get_text(url)
    soup = BeautifulSoup(html, "html.parser")
    block = soup.select_one("div.day7.hide.twty_hour")
    if block is None:
        raise ValueError(f"未找到 {city.name} 的 7 日天气模块")

    date_nodes = block.select("ul.week li b")
    weather_nodes = block.select("ul.txt.txt2 li")
    temp_nodes = block.select("div.zxt_shuju ul li")
    wind_lists = block.select("ul.txt")
    wind_direction_nodes = wind_lists[-1].select("li") if wind_lists else []

    records = []
    count = min(len(date_nodes), len(weather_nodes), len(temp_nodes))
    for index in range(count):
        max_temp = safe_float(temp_nodes[index].find("span").get_text(strip=True))
        min_temp = safe_float(temp_nodes[index].find("b").get_text(strip=True))
        detail = weather_nodes[index].get_text(strip=True)
        wind_direction = (
            wind_direction_nodes[index].get_text(strip=True) if index < len(wind_direction_nodes) else ""
        )
        records.append(
            {
                "city_slug": city.slug,
                "city_name": city.name,
                "date": cn_md_to_iso(date_nodes[index].get_text(strip=True), reference_date=date.today()),
                "weather_detail": detail,
                "weather_type": normalize_weather_type(detail),
                "max_temp": max_temp,
                "min_temp": min_temp,
                "avg_temp": compute_avg_temp(max_temp, min_temp),
                "wind_direction": wind_direction,
                "source_name": "tianqi.com",
            }
        )

    return {"url": url, "records": records, "raw_length": len(html)}


def fetch_forecast_api(city: CityConfig, client: HttpClient | None = None) -> dict:
    http_client = client or HttpClient()
    url = build_forecast_api_url(city)
    payload = http_client.get_json(url)
    daily = payload.get("daily", {})
    records = []
    for index, day in enumerate(daily.get("time", [])):
        max_temp = safe_float(daily.get("temperature_2m_max", [None])[index])
        min_temp = safe_float(daily.get("temperature_2m_min", [None])[index])
        wind_speed = safe_float(daily.get("wind_speed_10m_max", [None])[index])
        weather_detail = weather_code_to_cn(daily.get("weather_code", [None])[index])
        precipitation_mm = safe_float(daily.get("precipitation_sum", [None])[index], 0.0)
        records.append(
            {
                "city_slug": city.slug,
                "city_name": city.name,
                "date": day,
                "weather_detail_api": weather_detail,
                "weather_type_api": normalize_weather_type(weather_detail),
                "max_temp_api": max_temp,
                "min_temp_api": min_temp,
                "avg_temp_api": compute_avg_temp(max_temp, min_temp),
                "wind_speed_kmh": wind_speed,
                "wind_level": wind_speed_to_level(wind_speed),
                "precipitation_mm": precipitation_mm,
                "source_name_api": "open-meteo forecast",
            }
        )

    return {"url": url, "records": records, "daily_units": payload.get("daily_units", {})}
