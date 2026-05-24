from __future__ import annotations

from dataclasses import asdict

from config.cities import CITIES, CITY_BY_SLUG, CityConfig
from config.sources import build_geocoding_api_url
from crawler.fetcher import HttpClient


def _geo_slug(record: dict) -> str:
    geo_id = record.get("id")
    if geo_id:
        return f"geo-{geo_id}"
    latitude = int(round(float(record.get("latitude", 0.0)) * 10000))
    longitude = int(round(float(record.get("longitude", 0.0)) * 10000))
    return f"geo-{abs(latitude)}-{abs(longitude)}"


def _city_from_geocoding_record(record: dict) -> CityConfig:
    return CityConfig(
        slug=_geo_slug(record),
        name=record.get("name") or record.get("admin1") or "未知城市",
        pinyin=_geo_slug(record),
        latitude=float(record["latitude"]),
        longitude=float(record["longitude"]),
    )


def search_cities(query: str, client: HttpClient | None = None) -> list[dict]:
    cleaned = query.strip()
    if not cleaned:
        return []

    fixed_matches = [
        {
            **asdict(city),
            "province": "内置城市",
            "country": "中国",
            "source": "local",
            "display_name": city.name,
        }
        for city in CITIES
        if cleaned.lower() in city.name.lower() or cleaned.lower() in city.pinyin.lower()
    ]

    http_client = client or HttpClient()
    payload = http_client.get_json(build_geocoding_api_url(cleaned))
    remote_matches = []
    seen_slugs = {item["slug"] for item in fixed_matches}
    for record in payload.get("results", []) or []:
        if "latitude" not in record or "longitude" not in record:
            continue
        city = _city_from_geocoding_record(record)
        if city.slug in seen_slugs:
            continue
        seen_slugs.add(city.slug)
        province = record.get("admin1") or record.get("admin2") or ""
        country = record.get("country") or ""
        remote_matches.append(
            {
                **asdict(city),
                "province": province,
                "country": country,
                "source": "open-meteo geocoding",
                "display_name": " · ".join(part for part in [city.name, province, country] if part),
            }
        )

    return (fixed_matches + remote_matches)[:8]


def city_from_search_payload(payload: dict) -> CityConfig:
    slug = payload.get("slug", "").strip()
    if slug in CITY_BY_SLUG:
        return CITY_BY_SLUG[slug]
    return CityConfig(
        slug=slug,
        name=payload.get("name", "").strip() or "搜索城市",
        pinyin=slug,
        latitude=float(payload["latitude"]),
        longitude=float(payload["longitude"]),
    )
