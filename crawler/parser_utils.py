from __future__ import annotations

from datetime import date, datetime


def safe_float(value, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def compute_avg_temp(max_temp: float | None, min_temp: float | None) -> float | None:
    if max_temp is None or min_temp is None:
        return None
    return round((max_temp + min_temp) / 2, 1)


def cn_md_to_iso(md_text: str, reference_date: date | None = None) -> str:
    reference = reference_date or date.today()
    month_text, day_text = md_text.replace("日", "").split("月")
    month = int(month_text)
    day = int(day_text)
    year = reference.year
    candidate = date(year, month, day)
    if candidate < reference and reference.month == 12 and month == 1:
        candidate = date(year + 1, month, day)
    return candidate.isoformat()


def weather_code_to_cn(code: int | None) -> str:
    mapping = {
        0: "晴",
        1: "晴间多云",
        2: "多云",
        3: "阴",
        45: "雾",
        48: "雾凇",
        51: "毛毛雨",
        53: "小雨",
        55: "中雨",
        56: "冻雨",
        57: "冻雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        66: "冻雨",
        67: "冻雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        77: "雪粒",
        80: "阵雨",
        81: "阵雨",
        82: "强阵雨",
        85: "阵雪",
        86: "大雪",
        95: "雷阵雨",
        96: "雷阵雨",
        99: "强雷阵雨",
    }
    return mapping.get(code or 0, "未知")


def normalize_weather_type(detail: str | None) -> str:
    text = (detail or "").strip()
    if not text:
        return "未知"

    segments = [segment.strip() for segment in text.replace("/", "转").split("转") if segment.strip()]
    severity_order = {
        "暴雨": 7,
        "大雨": 6,
        "中雨": 5,
        "小雨": 4,
        "雨": 4,
        "大雪": 6,
        "中雪": 5,
        "小雪": 4,
        "雪": 4,
        "雷": 5,
        "雾": 3,
        "霾": 3,
        "阴": 2,
        "多云": 1,
        "晴": 0,
    }

    def classify(segment: str) -> tuple[int, str]:
        for keyword, level in severity_order.items():
            if keyword in segment:
                if keyword in ("暴雨", "大雨", "中雨", "小雨", "雨", "雷"):
                    return level, "雨"
                if keyword in ("大雪", "中雪", "小雪", "雪"):
                    return level, "雪"
                if keyword in ("雾", "霾"):
                    return level, "雾霾"
                if keyword == "阴":
                    return level, "阴"
                if keyword == "多云":
                    return level, "多云"
                if keyword == "晴":
                    return level, "晴"
        return -1, "未知"

    classified = [classify(segment) for segment in segments] or [classify(text)]
    classified.sort(key=lambda item: item[0], reverse=True)
    return classified[0][1]


def infer_rain_flag(detail: str | None, precipitation_mm: float | None = None) -> int:
    if precipitation_mm is not None and precipitation_mm >= 0.1:
        return 1
    text = detail or ""
    return 1 if any(token in text for token in ["雨", "雷", "雪"]) else 0


def wind_speed_to_level(speed_kmh: float | None) -> int | None:
    if speed_kmh is None:
        return None
    thresholds = [1, 5, 11, 19, 28, 38, 49, 61, 74, 88, 102, 117]
    for index, threshold in enumerate(thresholds):
        if speed_kmh <= threshold:
            return index
    return 12


def to_iso_timestamp(dt: datetime | None = None) -> str:
    return (dt or datetime.now()).replace(microsecond=0).isoformat(timespec="seconds")
