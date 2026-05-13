from __future__ import annotations

from datetime import date, timedelta

from config.cities import CityConfig


REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

REQUEST_TIMEOUT = 20


def build_forecast_page_url(city: CityConfig) -> str:
    return f"https://www.tianqi.com/{city.pinyin}/"


def build_forecast_api_url(city: CityConfig) -> str:
    return (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={city.latitude}"
        f"&longitude={city.longitude}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,weather_code"
        "&forecast_days=7"
        "&timezone=Asia%2FShanghai"
    )


def build_air_quality_api_url(city: CityConfig) -> str:
    return (
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={city.latitude}"
        f"&longitude={city.longitude}"
        "&hourly=us_aqi,pm2_5,pm10,ozone,nitrogen_dioxide,sulphur_dioxide,carbon_monoxide"
        "&forecast_days=5"
        "&timezone=Asia%2FShanghai"
    )


def build_history_api_url(city: CityConfig, start_date: date, end_date: date) -> str:
    return (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={city.latitude}"
        f"&longitude={city.longitude}"
        f"&start_date={start_date.isoformat()}"
        f"&end_date={end_date.isoformat()}"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,weather_code"
        "&timezone=Asia%2FShanghai"
    )


def default_history_range(today: date | None = None) -> tuple[date, date]:
    reference_today = today or date.today()
    first_day_of_current_month = reference_today.replace(day=1)
    end_date = first_day_of_current_month - timedelta(days=1)
    start_date = date(end_date.year - 2, 1, 1)
    return start_date, end_date
