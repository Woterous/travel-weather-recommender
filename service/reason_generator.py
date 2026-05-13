from __future__ import annotations

from config.preferences import preference_label


def build_preference_hint(preferences: dict) -> str:
    return (
        f"偏好模式为{preference_label('travel_style', preferences['travel_style'])}，"
        f"{preference_label('rain_sensitivity', preferences['rain_sensitivity'])}。"
    )


def generate_reason(row: dict, breakdown: dict, preferences: dict, history_baseline: dict | None) -> str:
    top_dimension = max(breakdown.items(), key=lambda item: item[1]["weighted_score"])[0]
    low_dimension = min(breakdown.items(), key=lambda item: item[1]["weighted_score"])[0]
    positive_labels = {
        "temperature": "温度舒适",
        "rain": "降雨风险较低",
        "wind": "风力较温和",
        "weather": "天气类型友好",
        "history": "历史月度稳定性较好",
        "aqi": "空气质量良好",
    }
    negative_labels = {
        "temperature": "温度区间不在最佳舒适带",
        "rain": "降雨拉低了当天表现",
        "wind": "风力对出行舒适度有拖累",
        "weather": "天气类型不够理想",
        "history": "历史月度稳定性一般",
        "aqi": "空气质量没有提供额外加分",
    }

    avg_temp = row.get("avg_temp")
    rain_text = "有降水" if row.get("rain_flag") else "降水风险低"
    aqi_value = row.get("aqi")
    aqi_text = ""
    if aqi_value is not None:
        try:
            aqi_number = float(aqi_value)
            if aqi_number == aqi_number:
                aqi_text = f"AQI 约 {aqi_number:.0f}。"
        except (TypeError, ValueError):
            aqi_text = ""
    history_text = ""
    if history_baseline:
        comfort = float(history_baseline.get("comfortable_days_ratio", 0.0)) * 100
        history_text = f"历史同月舒适天占比约 {comfort:.0f}% 。"

    return (
        f"{row['city_name']} {row['date']} 预计 {row.get('weather_detail', row.get('weather_type', '未知天气'))}，"
        f"均温 {avg_temp:.1f}℃，{rain_text}。"
        f"{build_preference_hint(preferences)}"
        f"{aqi_text}"
        f"主要加分项是{positive_labels.get(top_dimension, top_dimension)}，"
        f"主要扣分项是{negative_labels.get(low_dimension, low_dimension)}。"
        f"{history_text}"
    )


def generate_summary(reason: str) -> str:
    if len(reason) <= 48:
        return reason
    return reason[:48] + "..."
