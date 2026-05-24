from __future__ import annotations

import os

from config.preferences import normalize_preferences
from service.ranking import build_homepage_context


def call_external_ai_provider(prompt: str, context: dict) -> str | None:
    endpoint = os.getenv("TRAVEL_AI_ENDPOINT")
    api_key = os.getenv("TRAVEL_AI_API_KEY")
    if not endpoint or not api_key:
        return None
    return None


def answer_with_local_data(message: str, repository, preferences: dict) -> dict:
    dates = repository.get_forecast_dates()
    selected_date = dates[0] if dates else ""
    if not selected_date:
        return {
            "answer": "当前数据库还没有可用天气数据。请先刷新数据，再询问城市推荐、AQI 或对比结果。",
            "mode": "local",
        }

    context = build_homepage_context(repository, selected_date, preferences)
    ranking = context["ranking"]
    if not ranking:
        return {"answer": "当前日期没有可展示的推荐结果。", "mode": "local"}

    text = message.strip()
    top = ranking[0]
    mentioned = next((row for row in ranking if row["city_name"] in text or row["city_slug"] in text.lower()), None)

    if any(keyword in text for keyword in ["空气", "AQI", "aqi", "污染"]):
        rows = []
        for row in ranking:
            aqi = row.get("aqi")
            if aqi is not None and aqi == aqi:
                rows.append(row)
        rows.sort(key=lambda item: item.get("aqi") or 9999)
        if rows:
            best = rows[0]
            answer = (
                f"{selected_date} 空气质量相对更好的是 {best['city_name']}，AQI 约 {best['aqi']:.0f}。"
                f"当前综合推荐第一是 {top['city_name']}，总分 {top['score_total']}。"
            )
        else:
            answer = "当前推荐数据里还没有可用 AQI。"
    elif mentioned:
        answer = (
            f"{mentioned['city_name']} 在 {selected_date} 的综合分是 {mentioned['score_total']}，"
            f"规则分 {mentioned['rule_score']}，机器学习预测分 {mentioned['ml_score']}。"
            f"{mentioned['reason']}"
        )
    else:
        answer = (
            f"{selected_date} 当前最推荐 {top['city_name']}，综合分 {top['score_total']}。"
            f"规则分 {top['rule_score']}，机器学习预测分 {top['ml_score']}，"
            f"模型置信度 {top['ml_confidence']:.0%}。{top['reason']}"
        )

    external = call_external_ai_provider(text, {"selected_date": selected_date, "ranking": ranking[:5]})
    return {
        "answer": external or answer,
        "mode": "external" if external else "local",
        "selected_date": selected_date,
    }


def answer_assistant_message(message: str, repository, raw_preferences) -> dict:
    preferences = normalize_preferences(raw_preferences or {})
    return answer_with_local_data(message, repository, preferences)
