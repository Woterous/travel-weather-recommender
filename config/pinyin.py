from __future__ import annotations

import re

try:
    from pypinyin import lazy_pinyin
except ImportError:  # pragma: no cover
    lazy_pinyin = None


KNOWN_CITY_PINYIN = {
    "广州": "guangzhou",
    "天津": "tianjin",
    "天水": "tianshui",
    "哈尔滨": "haerbin",
    "青岛": "qingdao",
    "三亚": "sanya",
}


def city_name_to_pinyin(name: str) -> str:
    cleaned = re.sub(r"(特别行政区|自治州|自治县|地区|盟|市|区|县|旗)$", "", (name or "").strip())
    if not cleaned:
        return ""
    if cleaned in KNOWN_CITY_PINYIN:
        return KNOWN_CITY_PINYIN[cleaned]
    if lazy_pinyin is None:
        return ""
    return "".join(lazy_pinyin(cleaned))


def is_tianqi_slug(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z]+", (value or "").strip()))
