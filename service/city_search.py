from __future__ import annotations

import csv
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from config.cities import CITY_BY_SLUG, CityConfig
from config.sources import build_geocoding_api_url
from crawler.fetcher import HttpClient


REFERENCE_DIR = Path(__file__).resolve().parent / "reference"
CHINA_ADMIN_GEOCODES = REFERENCE_DIR / "china_admin_geocodes.csv"
MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}
AUTONOMOUS_REGION_SHORT_NAMES = {
    "广西壮族自治区": "广西",
    "内蒙古自治区": "内蒙古",
    "西藏自治区": "西藏",
    "宁夏回族自治区": "宁夏",
    "新疆维吾尔自治区": "新疆",
}
PROVINCE_SUFFIXES = ["特别行政区", "自治区", "省", "市"]
REGION_SUFFIXES = [
    "特别行政区",
    "自治区",
    "自治州",
    "自治县",
    "地区",
    "盟",
    "省",
    "市",
    "区",
    "县",
    "旗",
]


def _short_admin_name(name: str) -> str:
    for suffix in REGION_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def _split_province(full_name: str) -> tuple[str, str]:
    candidates = []
    for suffix in PROVINCE_SUFFIXES:
        marker = full_name.find(suffix)
        if marker >= 0:
            candidates.append((marker + len(suffix), suffix))
    if candidates:
        if any(suffix == "自治区" for _end, suffix in candidates):
            end = next(end for end, suffix in candidates if suffix == "自治区")
        else:
            end = min(end for end, _suffix in candidates)
            return full_name[:end], full_name[end:]
    return "", full_name


def _province_aliases(province: str) -> list[str]:
    aliases = [province]
    if province in AUTONOMOUS_REGION_SHORT_NAMES:
        aliases.append(AUTONOMOUS_REGION_SHORT_NAMES[province])
    for suffix in PROVINCE_SUFFIXES:
        if province.endswith(suffix):
            aliases.append(province[: -len(suffix)])
    return [alias for alias in aliases if alias]


def _remove_prefix(text: str, prefixes: list[str]) -> str:
    for prefix in sorted(prefixes, key=len, reverse=True):
        if prefix and text.startswith(prefix):
            return text[len(prefix) :]
    return text


def _local_slug(code: str) -> str:
    return f"cn-{code}"


@lru_cache(maxsize=1)
def _load_china_admin_index() -> list[dict]:
    if not CHINA_ADMIN_GEOCODES.exists():
        return []
    with CHINA_ADMIN_GEOCODES.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    by_code = {row["行政代码"]: row for row in rows}
    index = []
    for row in rows:
        code = row["行政代码"].strip()
        full_name = row["地名"].strip()
        province_row = by_code.get(f"{code[:2]}0000")
        province = province_row["地名"].strip() if province_row else _split_province(full_name)[0]
        if not province:
            continue
        province_aliases = _province_aliases(province)
        city = ""
        if code[2:] == "0000":
            name = province
        elif code[4:] == "00":
            name = _remove_prefix(full_name, province_aliases)
            if not name and province in MUNICIPALITIES:
                name = province
        else:
            parent = by_code.get(f"{code[:4]}00")
            if parent:
                parent_name = parent["地名"].strip()
                city = _remove_prefix(parent_name, province_aliases)
                if not city or city in {"市辖区", "县"}:
                    city = province
                if full_name.startswith(parent_name):
                    name = full_name[len(parent_name) :]
                else:
                    name = _remove_prefix(full_name, province_aliases)
            elif province in MUNICIPALITIES:
                city = province
                name = _remove_prefix(full_name, province_aliases)
            else:
                name = _remove_prefix(full_name, province_aliases)
        if city and name.startswith(city) and name != city:
            name = name[len(city) :]
        if name in {"市辖区", "市辖", "县"}:
            continue
        hierarchy = ["中国", province]
        if city and city != province:
            hierarchy.append(city)
        if name and name not in {province, city}:
            hierarchy.append(name)
        short_name = AUTONOMOUS_REGION_SHORT_NAMES.get(name, _short_admin_name(name))
        display_name = "·".join(hierarchy)
        index.append(
            {
                "slug": _local_slug(code),
                "name": short_name,
                "pinyin": code,
                "latitude": float(row["北纬"]),
                "longitude": float(row["东经"]),
                "province": province,
                "country": "中国",
                "source": "local admin geocodes",
                "display_name": display_name,
                "search_text": f"{full_name} {display_name} {short_name} {code}".lower(),
            }
        )
    return index


def _dedupe_city_results(results: list[dict]) -> list[dict]:
    deduped = []
    seen_keys = set()
    for item in results:
        key = str(item.get("slug") or item.get("display_name") or item.get("name") or "").strip().lower()
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(item)
    return deduped


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


def search_cities(query: str, client: HttpClient | None = None, include_remote: bool = True) -> list[dict]:
    cleaned = query.strip()
    if not cleaned:
        return []
    lowered = cleaned.lower()

    admin_matches = [item for item in _load_china_admin_index() if lowered in item["search_text"]]
    admin_matches.sort(
        key=lambda item: (
            0 if item["name"] == cleaned else 1 if item["name"].startswith(cleaned) else 2,
            len(item["display_name"]),
            item["display_name"],
        )
    )

    local_matches = admin_matches
    has_exact_local_match = any(item["name"].lower() == cleaned.lower() for item in local_matches)
    should_search_remote = include_remote and len(cleaned) > 1 and not has_exact_local_match

    payload = {"results": []}
    if should_search_remote:
        http_client = client or HttpClient()
        try:
            payload = http_client.get_json(build_geocoding_api_url(cleaned))
        except Exception:
            payload = {"results": []}
    remote_matches = []
    seen_slugs = {item["slug"] for item in local_matches}
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
                "display_name": "·".join(part for part in [country, province, city.name] if part),
            }
        )

    return _dedupe_city_results(local_matches + remote_matches)[:15]


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
