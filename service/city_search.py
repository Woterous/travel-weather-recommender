from __future__ import annotations

from dataclasses import asdict

from config.cities import CITIES, CITY_BY_SLUG, CityConfig
from config.sources import build_geocoding_api_url
from crawler.fetcher import HttpClient


CURATED_CITY_SUGGESTIONS = [
    CityConfig("geo-1809858", "广州", "guangzhou", 23.11667, 113.25),
    CityConfig("geo-1811720", "广元", "guangyuan", 32.44201, 105.823),
    CityConfig("geo-1812256", "广安", "guangan", 30.47413, 106.63696),
    CityConfig("geo-10179231", "广陵", "guangling", 32.39358, 119.43157),
    CityConfig("geo-1806466", "广德", "guangde", 30.89371, 119.41705),
    CityConfig("geo-1814906", "长沙", "changsha", 28.19874, 112.97087),
    CityConfig("geo-1795565", "苏州", "suzhou", 31.30408, 120.59538),
    CityConfig("geo-1816670", "深圳", "shenzhen", 22.54554, 114.0683),
]


def _city_to_search_result(city: CityConfig, province: str, source: str, country: str = "中国") -> dict:
    return {
        **asdict(city),
        "province": province,
        "country": country,
        "source": source,
        "display_name": " · ".join(part for part in [city.name, province, country] if part),
    }


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
        _city_to_search_result(city, province="内置城市", source="local")
        for city in CITIES
        if cleaned.lower() in city.name.lower() or cleaned.lower() in city.pinyin.lower()
    ]
    curated_matches = [
        _city_to_search_result(city, province="联想城市", source="local suggestion")
        for city in CURATED_CITY_SUGGESTIONS
        if cleaned.lower() in city.name.lower() or cleaned.lower() in city.pinyin.lower()
    ]

    http_client = client or HttpClient()
    payload = {"results": []}
    try:
        payload = http_client.get_json(build_geocoding_api_url(cleaned))
    except Exception:
        payload = {"results": []}
    remote_matches = []
    seen_slugs = {item["slug"] for item in fixed_matches + curated_matches}
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

    return (fixed_matches + curated_matches + remote_matches)[:8]


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
