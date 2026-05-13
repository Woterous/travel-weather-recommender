from __future__ import annotations

from collections import defaultdict

from config.cities import CityConfig
from config.sources import build_air_quality_api_url
from crawler.fetcher import HttpClient
from crawler.parser_utils import safe_float


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _maximum(values: list[float]) -> float | None:
    if not values:
        return None
    return round(max(values), 1)


def fetch_air_quality_api(city: CityConfig, client: HttpClient | None = None) -> dict:
    http_client = client or HttpClient()
    url = build_air_quality_api_url(city)
    payload = http_client.get_json(url)
    hourly = payload.get("hourly", {})

    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    times = hourly.get("time", [])
    variables = [
        "us_aqi",
        "pm2_5",
        "pm10",
        "ozone",
        "nitrogen_dioxide",
        "sulphur_dioxide",
        "carbon_monoxide",
    ]

    for index, timestamp in enumerate(times):
        day = str(timestamp)[:10]
        if not day:
            continue
        for variable in variables:
            values = hourly.get(variable, [])
            value = safe_float(values[index] if index < len(values) else None)
            if value is not None:
                grouped[day][variable].append(value)

    records = []
    for day in sorted(grouped):
        values = grouped[day]
        records.append(
            {
                "city_slug": city.slug,
                "city_name": city.name,
                "date": day,
                "aqi": _maximum(values.get("us_aqi", [])),
                "pm2_5_avg": _average(values.get("pm2_5", [])),
                "pm10_avg": _average(values.get("pm10", [])),
                "ozone_avg": _average(values.get("ozone", [])),
                "nitrogen_dioxide_avg": _average(values.get("nitrogen_dioxide", [])),
                "sulphur_dioxide_avg": _average(values.get("sulphur_dioxide", [])),
                "carbon_monoxide_avg": _average(values.get("carbon_monoxide", [])),
                "source_name": "open-meteo air quality",
            }
        )

    return {"url": url, "records": records, "hourly_units": payload.get("hourly_units", {})}
