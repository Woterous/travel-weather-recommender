from __future__ import annotations

from config.cities import CityConfig
from config.sources import build_history_api_url, default_history_range
from crawler.fetcher import HttpClient
from crawler.parser_utils import compute_avg_temp, safe_float, weather_code_to_cn


def fetch_history_daily(city: CityConfig, client: HttpClient | None = None) -> dict:
    http_client = client or HttpClient()
    start_date, end_date = default_history_range()
    url = build_history_api_url(city, start_date, end_date)
    payload = http_client.get_json(url)
    daily = payload.get("daily", {})
    records = []
    for index, day in enumerate(daily.get("time", [])):
        max_temp = safe_float(daily.get("temperature_2m_max", [None])[index])
        min_temp = safe_float(daily.get("temperature_2m_min", [None])[index])
        wind_speed = safe_float(daily.get("wind_speed_10m_max", [None])[index])
        precipitation_mm = safe_float(daily.get("precipitation_sum", [None])[index], 0.0)
        records.append(
            {
                "city_slug": city.slug,
                "city_name": city.name,
                "date": day,
                "max_temp": max_temp,
                "min_temp": min_temp,
                "avg_temp": compute_avg_temp(max_temp, min_temp),
                "weather_detail": weather_code_to_cn(daily.get("weather_code", [None])[index]),
                "precipitation_mm": precipitation_mm,
                "wind_speed_kmh": wind_speed,
            }
        )

    return {
        "url": url,
        "records": records,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
