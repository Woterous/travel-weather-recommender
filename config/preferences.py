from urllib.parse import urlencode


DEFAULT_PREFERENCES = {
    "rain_sensitivity": "medium",
    "temperature_preference": "mild",
    "wind_sensitivity": "medium",
    "travel_style": "general",
    "aqi_sensitivity": "medium",
}

PREFERENCE_OPTIONS = {
    "rain_sensitivity": [
        ("high", "强烈怕下雨"),
        ("medium", "一般怕下雨"),
        ("low", "不太在意下雨"),
    ],
    "temperature_preference": [
        ("cool", "喜欢凉爽"),
        ("mild", "喜欢温和"),
        ("warm", "喜欢偏暖"),
    ],
    "wind_sensitivity": [
        ("high", "很怕大风"),
        ("medium", "一般"),
        ("low", "不太在意"),
    ],
    "travel_style": [
        ("general", "通用模式"),
        ("citywalk", "城市漫步型"),
        ("outdoor", "户外自然型"),
        ("seaside", "海滨休闲型"),
    ],
    "aqi_sensitivity": [
        ("high", "非常在意空气质量"),
        ("medium", "一般在意"),
        ("low", "不太在意"),
    ],
}


def normalize_preferences(raw_mapping) -> dict:
    cleaned = {}
    for key, default_value in DEFAULT_PREFERENCES.items():
        allowed = {value for value, _label in PREFERENCE_OPTIONS[key]}
        value = raw_mapping.get(key, default_value)
        cleaned[key] = value if value in allowed else default_value
    return cleaned


def preference_label(key: str, value: str) -> str:
    labels = {option_value: label for option_value, label in PREFERENCE_OPTIONS[key]}
    return labels.get(value, value)


def preferences_to_query(preferences: dict, extra: dict | None = None) -> str:
    params = dict(preferences)
    if extra:
        params.update({key: value for key, value in extra.items() if value is not None})
    return urlencode(params)
