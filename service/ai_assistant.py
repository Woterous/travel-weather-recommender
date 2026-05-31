from __future__ import annotations

import os
import re
from datetime import date, timedelta

from config.preferences import PREFERENCE_OPTIONS, normalize_preferences, preference_label
from service.compare import build_compare_context
from service.history_analysis import get_history_ranking
from service.ranking import build_homepage_context


PREFERENCE_KEYS = set(PREFERENCE_OPTIONS.keys())


def call_external_ai_provider(prompt: str, context: dict) -> str | None:
    endpoint = os.getenv("TRAVEL_AI_ENDPOINT")
    api_key = os.getenv("TRAVEL_AI_API_KEY")
    if not endpoint or not api_key:
        return None
    return None


def _safe_number(value, precision: int = 1, suffix: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if number != number:
        return "-"
    if precision == 0:
        return f"{number:.0f}{suffix}"
    return f"{number:.{precision}f}{suffix}"


def _forecast_date(repository, requested_date: str | None, message: str = "") -> str:
    dates = repository.get_forecast_dates()
    if not dates:
        return ""

    today = date.today()
    date_aliases = {
        "今天": today.isoformat(),
        "今日": today.isoformat(),
        "明天": (today + timedelta(days=1)).isoformat(),
        "后天": (today + timedelta(days=2)).isoformat(),
    }
    for keyword, date_text in date_aliases.items():
        if keyword in message and date_text in dates:
            return date_text

    explicit = re.search(r"20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2}", message)
    if explicit:
        normalized = (
            explicit.group(0)
            .replace("年", "-")
            .replace("月", "-")
            .replace("/", "-")
            .replace(".", "-")
            .replace("日", "")
        )
        parts = [part for part in normalized.split("-") if part]
        if len(parts) == 3:
            date_text = f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            if date_text in dates:
                return date_text

    if requested_date in dates:
        return requested_date or ""

    for date_text in dates:
        if date_text >= today.isoformat():
            return date_text
    return dates[-1]


def _context_preferences(payload: dict) -> dict:
    raw_preferences = payload.get("preferences") if isinstance(payload, dict) else {}
    if not isinstance(raw_preferences, dict):
        raw_preferences = {}
    merged = {key: payload.get(key) for key in PREFERENCE_KEYS if isinstance(payload, dict) and payload.get(key)}
    merged.update(raw_preferences)
    return normalize_preferences(merged)


def _city_options(repository) -> list[dict]:
    options = repository.get_available_cities()
    if options:
        return options
    return []


def _find_city_mentions(message: str, ranking: list[dict], repository) -> list[dict]:
    text = message.lower()
    seen = set()
    matches = []
    ranked_by_slug = {str(row.get("city_slug", "")).lower(): row for row in ranking}
    for row in ranking:
        names = [
            str(row.get("city_name", "")),
            str(row.get("city_slug", "")),
        ]
        if any(name and name.lower() in text for name in names):
            slug = str(row.get("city_slug", ""))
            if slug not in seen:
                seen.add(slug)
                matches.append(row)

    for city in _city_options(repository):
        slug = str(city.get("slug", ""))
        name = str(city.get("name", ""))
        if slug in seen:
            continue
        if (name and name in message) or (slug and slug.lower() in text):
            seen.add(slug)
            matches.append(ranked_by_slug.get(slug.lower()) or {"city_slug": slug, "city_name": name})
    return matches


def _append_context_city_mentions(payload: dict, mentions: list[dict], ranking: list[dict], repository) -> list[dict]:
    if not isinstance(payload, dict):
        return mentions
    by_slug = {str(row.get("city_slug", "")): row for row in ranking}
    city_names = {str(city.get("slug", "")): str(city.get("name", "")) for city in _city_options(repository)}
    context_slugs = []
    for key in ["current_city_slug", "city_a", "city_b"]:
        value = str(payload.get(key, "")).strip()
        if value:
            context_slugs.append(value)
    seen = {str(row.get("city_slug", "")) for row in mentions}
    enriched = list(mentions)
    for slug in context_slugs:
        if slug in seen:
            continue
        seen.add(slug)
        enriched.append(by_slug.get(slug) or {"city_slug": slug, "city_name": city_names.get(slug, slug)})
    return enriched


def _row_summary(row: dict) -> str:
    return (
        f"{row['city_name']}综合分{_safe_number(row.get('score_total'))}，"
        f"天气{row.get('weather_detail', '-') }，均温{_safe_number(row.get('avg_temp'), 1, '℃')}，"
        f"降水{'有风险' if row.get('rain_flag') else '风险低'}，"
        f"AQI{_safe_number(row.get('aqi'), 0)}。"
    )


def _answer_recommendation(selected_date: str, ranking: list[dict]) -> str:
    top = ranking[0]
    next_rows = "、".join(
        f"{row['city_name']}({_safe_number(row.get('score_total'))})"
        for row in ranking[1:4]
    )
    suffix = f" 备选城市：{next_rows}。" if next_rows else ""
    return (
        f"{selected_date} 当前最推荐 {top['city_name']}，综合分 {_safe_number(top.get('score_total'))}。"
        f"{top.get('reason', '')}{suffix}"
    )


def _answer_city(selected_date: str, row: dict) -> str:
    if not row.get("score_total"):
        return f"当前日期没有找到 {row.get('city_name', '该城市')} 的推荐评分，可能需要先刷新这个城市的数据。"
    return (
        f"{row['city_name']} 在 {selected_date} 的表现是：{_row_summary(row)}"
        f"规则分{_safe_number(row.get('rule_score'))}，"
        f"机器学习预测分{_safe_number(row.get('ml_score'))}，"
        f"模型置信度{_safe_number(float(row.get('ml_confidence') or 0) * 100, 0, '%')}。"
        f"{row.get('reason', '')}"
    )


def _answer_aqi(selected_date: str, ranking: list[dict], mentioned: dict | None = None) -> str:
    rows = [row for row in ranking if _safe_number(row.get("aqi"), 0) != "-"]
    if not rows:
        return "当前推荐数据里还没有可用 AQI，空气质量相关问题暂时只能等刷新后再判断。"
    if mentioned and _safe_number(mentioned.get("aqi"), 0) != "-":
        return (
            f"{mentioned['city_name']} 在 {selected_date} 的 AQI 约 {_safe_number(mentioned.get('aqi'), 0)}，"
            f"AQI 维度得分 {_safe_number(mentioned.get('score_breakdown', {}).get('aqi', {}).get('score'))}。"
            f"综合分 {_safe_number(mentioned.get('score_total'))}。"
        )
    rows.sort(key=lambda item: float(item.get("aqi") or 9999))
    best = rows[0]
    worst = rows[-1]
    return (
        f"{selected_date} 空气质量相对最好的是 {best['city_name']}，AQI 约 {_safe_number(best.get('aqi'), 0)}。"
        f"当前 AQI 较高的是 {worst['city_name']}，AQI 约 {_safe_number(worst.get('aqi'), 0)}。"
    )


def _answer_compare(repository, selected_date: str, preferences: dict, city_a: dict, city_b: dict) -> str:
    slug_a = city_a.get("city_slug")
    slug_b = city_b.get("city_slug")
    if not slug_a or not slug_b:
        return "我需要两个城市才能做对比，例如：北京和上海哪个好？"
    context = build_compare_context(repository, slug_a, slug_b, selected_date, preferences)
    row_a = context.get("row_a")
    row_b = context.get("row_b")
    if not row_a or not row_b:
        return f"{selected_date} 这两个城市没有足够的对比数据，请先刷新数据或换一个日期。"
    winner = row_a if row_a["score_total"] >= row_b["score_total"] else row_b
    loser = row_b if winner is row_a else row_a
    diff = abs(float(row_a["score_total"]) - float(row_b["score_total"]))
    return (
        f"{selected_date} 更推荐 {winner['city_name']}。"
        f"{row_a['city_name']}综合分{_safe_number(row_a.get('score_total'))}，"
        f"{row_b['city_name']}综合分{_safe_number(row_b.get('score_total'))}，"
        f"分差{diff:.1f}。{winner['city_name']}的主要理由是：{winner.get('reason', '')}"
        f"{loser['city_name']}可作为备选。"
    )


def _answer_preference(preferences: dict, ranking: list[dict]) -> str:
    labels = [
        preference_label("travel_style", preferences["travel_style"]),
        preference_label("temperature_preference", preferences["temperature_preference"]),
        preference_label("rain_sensitivity", preferences["rain_sensitivity"]),
        preference_label("wind_sensitivity", preferences["wind_sensitivity"]),
        preference_label("aqi_sensitivity", preferences["aqi_sensitivity"]),
    ]
    top = ranking[0] if ranking else None
    top_text = f"在当前偏好下，第一推荐是 {top['city_name']}，综合分 {_safe_number(top.get('score_total'))}。" if top else ""
    return (
        f"当前偏好是：{'、'.join(labels)}。"
        "本地评分会按这些偏好调整温度、降雨、风力、天气类型、历史稳定性和 AQI 的权重。"
        f"{top_text}"
    )


def _answer_history(repository, message: str) -> str:
    history_df = repository.get_history_monthly()
    if history_df.empty:
        return "当前还没有历史月度统计数据，暂时无法回答历史稳定性问题。"
    month_match = re.search(r"(\d{1,2})\s*月", message)
    month_num = int(month_match.group(1)) if month_match else date.today().month
    if month_num < 1 or month_num > 12:
        month_num = date.today().month
    ranking = get_history_ranking(history_df, month_num, "suitability")
    if not ranking:
        return f"当前没有 {month_num} 月的历史稳定性数据。"
    top = ranking[0]
    return (
        f"从历史月度数据看，{month_num} 月稳定性较好的城市是 {top['city_name']}，"
        f"历史适宜度 {_safe_number(top.get('history_score'))}，"
        f"舒适天占比约 {_safe_number(float(top.get('comfortable_days_ratio') or 0) * 100, 0, '%')}，"
        f"雨天占比约 {_safe_number(float(top.get('rainy_ratio') or 0) * 100, 0, '%')}。"
    )


def answer_with_local_data(message: str, repository, payload: dict) -> dict:
    preferences = _context_preferences(payload)
    selected_date = _forecast_date(repository, payload.get("selected_date") or payload.get("date"), message)
    if not selected_date:
        return {
            "answer": "当前数据库还没有可用天气数据。请先刷新数据，再询问城市推荐、AQI 或对比结果。",
            "mode": "local",
        }

    context = build_homepage_context(repository, selected_date, preferences)
    ranking = context["ranking"]
    if not ranking:
        return {"answer": f"{selected_date} 当前没有可展示的推荐结果。", "mode": "local", "selected_date": selected_date}

    text = message.strip()
    explicit_mentions = _find_city_mentions(text, ranking, repository)
    city_mentions = _append_context_city_mentions(payload, explicit_mentions, ranking, repository)
    explicit_mentioned = explicit_mentions[0] if explicit_mentions else None
    mentioned = city_mentions[0] if city_mentions else None
    lower_text = text.lower()

    if any(keyword in text for keyword in ["历史", "稳定", "往年", "月度", "哪个月"]):
        answer = _answer_history(repository, text)
    elif any(keyword in text for keyword in ["对比", "哪个更", "哪个好", "哪一个好", "比"]) and len(city_mentions) >= 2:
        answer = _answer_compare(repository, selected_date, preferences, city_mentions[0], city_mentions[1])
    elif any(keyword in text for keyword in ["空气", "AQI", "aqi", "污染", "雾霾"]):
        answer = _answer_aqi(selected_date, ranking, explicit_mentioned)
    elif any(keyword in text for keyword in ["偏好", "模式", "怕下雨", "下雨", "户外", "城市漫步", "海滨", "温和", "凉爽", "偏暖"]):
        answer = _answer_preference(preferences, ranking)
    elif any(keyword in lower_text for keyword in ["recommend", "best"]) or any(keyword in text for keyword in ["推荐", "去哪", "去哪里", "哪个城市", "排行", "第一"]):
        answer = _answer_recommendation(selected_date, ranking)
    elif mentioned:
        answer = _answer_city(selected_date, mentioned)
    else:
        answer = (
            "我可以基于本地数据回答这些核心问题：今天推荐哪个城市、某个城市适不适合去、"
            "两个城市哪个好、哪个城市空气质量更好、当前偏好怎么影响推荐、历史稳定性如何。"
            f"当前日期是 {selected_date}，你也可以直接问“北京适合去吗？”或“北京和上海哪个好？”。"
        )

    external = call_external_ai_provider(text, {"selected_date": selected_date, "ranking": ranking[:5], "preferences": preferences})
    return {
        "answer": external or answer,
        "mode": "external" if external else "local",
        "selected_date": selected_date,
    }


def answer_assistant_message(message: str, repository, raw_payload) -> dict:
    payload = raw_payload if isinstance(raw_payload, dict) else {"preferences": raw_payload or {}}
    return answer_with_local_data(message, repository, payload)
