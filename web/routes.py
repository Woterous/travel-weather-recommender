from __future__ import annotations

import json
import math
from datetime import date
from threading import Thread
from types import SimpleNamespace
from urllib.parse import urlencode

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, stream_with_context, url_for

from config.cities import CITIES, CITY_BY_SLUG, DEFAULT_CITY_SLUG
from config.preferences import DEFAULT_PREFERENCES, PREFERENCE_OPTIONS, normalize_preferences, preference_label
from service.ai_assistant import answer_assistant_message
from service.city_search import city_from_search_payload, search_cities
from config.cities import CityConfig
from service.compare import build_compare_context
from service.database import WeatherRepository
from service.history_analysis import get_city_history_series, get_history_ranking, month_num_options
from service.pipeline import preview_city_forecast, refresh_all_data, refresh_city_data
from service.ranking import build_city_detail_context, build_homepage_context
from service.refresh_progress import refresh_jobs
from service.scoring import build_weights


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["SECRET_KEY"] = "travel-weather-recommender-dev"
    register_routes(app)
    return app


def _query_string(preferences: dict, extra: dict | None = None) -> str:
    params = dict(preferences)
    if extra:
        params.update({key: value for key, value in extra.items() if value is not None})
    return urlencode(params)


def _resolve_selected_date(requested_date: str | None, available_dates: list[str]) -> str:
    if not available_dates:
        return ""
    if requested_date and requested_date in available_dates:
        return requested_date
    return _preferred_forecast_date(available_dates)


def _preferred_forecast_date(available_dates: list[str]) -> str:
    today = date.today().isoformat()
    for date_text in available_dates:
        if date_text >= today:
            return date_text
    return available_dates[-1] if available_dates else ""


def _preferred_repository_forecast_date(repository: WeatherRepository) -> str:
    return _preferred_forecast_date(repository.get_forecast_dates())


def _aqi_display(value) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "-"
    if math.isnan(numeric):
        return "-"
    return f"{numeric:.0f}"


def _selected_search_city_from_args(args) -> dict | None:
    slug = args.get("candidate_slug", "").strip()
    if not slug:
        return None
    return {
        "slug": slug,
        "name": args.get("candidate_name", "").strip() or "搜索城市",
        "latitude": args.get("candidate_latitude", "").strip(),
        "longitude": args.get("candidate_longitude", "").strip(),
        "province": args.get("candidate_province", "").strip(),
        "country": args.get("candidate_country", "").strip(),
        "display_name": args.get("candidate_display_name", "").strip() or args.get("candidate_name", "").strip(),
    }


def _candidate_payload_from_args(args) -> dict:
    return {
        "slug": args.get("candidate_slug", "").strip(),
        "name": args.get("candidate_name", "").strip(),
        "latitude": args.get("candidate_latitude", "").strip(),
        "longitude": args.get("candidate_longitude", "").strip(),
        "province": args.get("candidate_province", "").strip(),
        "country": args.get("candidate_country", "").strip(),
        "display_name": args.get("candidate_display_name", "").strip(),
    }


def _city_for_detail(repository: WeatherRepository, city_slug: str):
    city_record = repository.get_city_record(city_slug)
    if city_record:
        return SimpleNamespace(
            slug=city_record["slug"],
            name=city_record["name"],
            pinyin=city_record["pinyin"],
            latitude=city_record["latitude"],
            longitude=city_record["longitude"],
        )
    city_meta = repository.get_city_meta(city_slug)
    if not city_meta:
        return None
    return SimpleNamespace(
        slug=city_meta["slug"],
        name=city_meta["name"],
        pinyin=city_meta["pinyin"],
        latitude=None,
        longitude=None,
    )


def _city_from_query(city_slug: str, args):
    name = args.get("name", "").strip()
    latitude = args.get("latitude", "").strip()
    longitude = args.get("longitude", "").strip()
    if not name or not latitude or not longitude:
        return None
    return CityConfig(city_slug, name, city_slug, float(latitude), float(longitude))


def register_routes(app: Flask) -> None:
    @app.context_processor
    def inject_globals():
        def query_with(preferences: dict, **extra) -> str:
            return _query_string(preferences, extra)

        return {
            "cities": CITIES,
            "preference_options": PREFERENCE_OPTIONS,
            "preference_label": preference_label,
            "query_with": query_with,
            "aqi_display": _aqi_display,
        }

    @app.get("/")
    def home():
        repository = WeatherRepository()
        dates = repository.get_forecast_dates()
        selected_date = _resolve_selected_date(request.args.get("date"), dates)
        preferences = normalize_preferences(request.args)
        search_query = request.args.get("q", "").strip()
        search_results = []
        search_error = ""
        selected_search_city = _selected_search_city_from_args(request.args)
        preview_weather = None
        preview_error = ""
        if search_query:
            try:
                search_results = search_cities(search_query)
            except Exception as exc:
                search_error = f"城市搜索失败：{exc}"
        if selected_search_city:
            try:
                preview_weather = preview_city_forecast(city_from_search_payload(_candidate_payload_from_args(request.args)))
            except Exception as exc:
                preview_error = f"当前天气预览失败：{exc}"
        context = (
            build_homepage_context(repository, selected_date, preferences)
            if selected_date
            else {
                "ranking": [],
                "chart_data": {"cities": [], "scores": []},
                "ml_predictions": [],
                "weights_preview": {},
                "aqi_available": False,
                "model_summary": {"name": "KNN 历史天气预测模型", "sample_count": 0, "mae": None},
            }
        )
        return render_template(
            "index.html",
            selected_date=selected_date,
            available_dates=dates,
            preferences=preferences,
            latest_refresh=repository.get_latest_refresh_info(),
            default_compare_city="shanghai",
            search_query=search_query,
            search_results=search_results,
            search_error=search_error,
            selected_search_city=selected_search_city,
            preview_weather=preview_weather,
            preview_error=preview_error,
            added_cities=repository.get_added_cities(),
            **context,
        )

    @app.route("/preferences", methods=["GET", "POST"])
    def preferences_page():
        if request.method == "POST":
            if request.form.get("action") == "reset":
                preferences = dict(DEFAULT_PREFERENCES)
            else:
                preferences = normalize_preferences(request.form)
            date_text = request.form.get("date") or ""
            return redirect(url_for("home") + "?" + _query_string(preferences, {"date": date_text}))

        repository = WeatherRepository()
        preferences = normalize_preferences(request.args)
        return render_template(
            "preference.html",
            preferences=preferences,
            default_preferences=DEFAULT_PREFERENCES,
            selected_date=request.args.get("date") or "",
            latest_refresh=repository.get_latest_refresh_info(),
            aqi_available=repository.aqi_available(),
            weights_preview=build_weights(preferences, aqi_available=repository.aqi_available()),
        )

    @app.get("/city/<city_slug>")
    def city_detail(city_slug: str):
        repository = WeatherRepository()
        preferences = normalize_preferences(request.args)
        dates = repository.get_forecast_dates()
        selected_date = _resolve_selected_date(request.args.get("date"), dates)
        city = _city_for_detail(repository, city_slug)
        if city is None:
            city = _city_from_query(city_slug, request.args)
        if city is None:
            flash("当前城市还没有本地数据，请先通过首页搜索该城市。", "warning")
            return redirect(url_for("home") + "?" + _query_string(preferences))
        context = build_city_detail_context(repository, city_slug, selected_date, preferences) if selected_date else {}
        autoload_city = request.args.get("autoload") == "1" and not context.get("selected")
        city_record = repository.get_city_record(city_slug)
        return render_template(
            "city_detail.html",
            city=city,
            selected_date=selected_date,
            available_dates=dates,
            preferences=preferences,
            latest_refresh=repository.get_latest_refresh_info(),
            autoload_city=autoload_city,
            city_in_library=city_record is not None,
            can_add_city_to_library=bool(city.latitude or request.args.get("latitude")),
            **context,
        )

    @app.get("/compare")
    def compare_page():
        repository = WeatherRepository()
        preferences = normalize_preferences(request.args)
        dates = repository.get_forecast_dates()
        selected_date = _resolve_selected_date(request.args.get("date"), dates)
        city_a = request.args.get("city_a") or DEFAULT_CITY_SLUG
        city_b = request.args.get("city_b") or "shanghai"
        context = build_compare_context(repository, city_a, city_b, selected_date, preferences) if selected_date else {}
        city_options = repository.get_available_cities() or [{"slug": city.slug, "name": city.name} for city in CITIES]
        return render_template(
            "compare.html",
            city_a=city_a,
            city_b=city_b,
            city_options=city_options,
            selected_date=selected_date,
            available_dates=dates,
            preferences=preferences,
            latest_refresh=repository.get_latest_refresh_info(),
            **context,
        )

    @app.get("/history")
    def history_page():
        repository = WeatherRepository()
        preferences = normalize_preferences(request.args)
        city_slug = request.args.get("city") or DEFAULT_CITY_SLUG
        metric = request.args.get("metric") or "suitability"
        history_df = repository.get_history_monthly()
        city_series = get_city_history_series(history_df, city_slug)
        month_options = month_num_options(history_df)
        selected_month = int(request.args.get("month", month_options[0] if month_options else 1))
        ranking = get_history_ranking(history_df, selected_month, metric)
        chart_data = {
            "months": [item["month_key"] for item in city_series],
            "history_scores": [item["history_score"] for item in city_series],
            "rainy_ratio": [round(float(item["rainy_ratio"]) * 100, 1) for item in city_series],
            "comfortable_ratio": [round(float(item["comfortable_days_ratio"]) * 100, 1) for item in city_series],
        }
        return render_template(
            "history.html",
            city=CITY_BY_SLUG[city_slug],
            selected_month=selected_month,
            month_options=month_options,
            metric=metric,
            history_series=city_series,
            ranking=ranking,
            chart_data=chart_data,
            preferences=preferences,
            latest_refresh=repository.get_latest_refresh_info(),
            aqi_available=repository.aqi_available(),
        )

    @app.post("/refresh")
    def refresh():
        result = refresh_all_data() ##刷新数据路由
        if result["errors"]:
            flash(result["message"], "warning")
        else:
            flash("数据刷新完成。", "success")
        preferences = normalize_preferences(request.form or request.args)
        date_text = _preferred_repository_forecast_date(WeatherRepository())
        return redirect(url_for("home") + "?" + _query_string(preferences, {"date": date_text}))

    @app.post("/refresh/start")
    def refresh_start():
        preferences = normalize_preferences(request.form or request.args)
        home_path = url_for("home")
        job_id = refresh_jobs.create()

        def run_refresh() -> None:
            def emit(event: dict) -> None:
                refresh_jobs.emit(job_id, event)

            try:
                result = refresh_all_data(progress_callback=emit)
                final_redirect_url = home_path + "?" + _query_string(preferences, {"date": _preferred_repository_forecast_date(WeatherRepository())})
                refresh_jobs.emit(
                    job_id,
                    {
                        "status": "warning" if result["errors"] else "done",
                        "stage": "刷新完成",
                        "message": result["message"],
                        "next_step": "正在重新加载首页。",
                        "redirect_url": final_redirect_url,
                    },
                )
            except Exception as exc:  # pragma: no cover
                refresh_jobs.emit(
                    job_id,
                    {
                        "status": "error",
                        "stage": "刷新失败",
                        "message": f"刷新过程中出现异常：{exc}",
                        "next_step": "请检查网络或稍后重试。",
                    },
                )

        Thread(target=run_refresh, daemon=True).start()
        return jsonify({"job_id": job_id})

    @app.get("/refresh/events/<job_id>")
    def refresh_events(job_id: str):
        @stream_with_context
        def generate():
            for event in refresh_jobs.listen(job_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    @app.post("/city/refresh")
    def refresh_city():
        preferences = normalize_preferences(request.form)
        date_text = request.form.get("date") or request.args.get("date") or ""
        city = city_from_search_payload(request.form)
        result = refresh_city_data(city)
        repository = WeatherRepository()
        repository.add_city_record(
            city,
            province=request.form.get("province", ""),
            country=request.form.get("country", ""),
        )
        if result["errors"]:
            flash(result["message"], "warning")
        else:
            flash(f"{city.name} 数据刷新完成。", "success")
        city_dates = repository.get_city_forecast(city.slug)
        target_date = _preferred_forecast_date(sorted(city_dates["date"].dropna().astype(str).unique())) if not city_dates.empty else date_text
        return redirect(url_for("city_detail", city_slug=city.slug) + "?" + _query_string(preferences, {"date": target_date}))

    @app.post("/city/refresh/start")
    def refresh_city_start():
        preferences = normalize_preferences(request.form)
        city = city_from_search_payload(request.form)
        province = request.form.get("province", "")
        country = request.form.get("country", "")
        city_detail_path = url_for("city_detail", city_slug=city.slug)
        job_id = refresh_jobs.create()

        def run_refresh() -> None:
            try:
                refresh_jobs.emit(job_id, {"status": "running", "step": 1, "total": 4, "stage": "加载详情", "message": f"正在准备 {city.name} 的天气数据。"})
                result = refresh_city_data(city)
                repository = WeatherRepository()
                city_dates = repository.get_city_forecast(city.slug)
                target_date = _preferred_forecast_date(sorted(city_dates["date"].dropna().astype(str).unique())) if not city_dates.empty else ""
                redirect_url = city_detail_path + "?" + _query_string(
                    preferences,
                    {
                        "date": target_date,
                        "name": city.name,
                        "latitude": city.latitude,
                        "longitude": city.longitude,
                        "province": province,
                        "country": country,
                    },
                )
                refresh_jobs.emit(
                    job_id,
                    {
                        "status": "warning" if result["errors"] else "done",
                        "step": 4,
                        "total": 4,
                        "stage": "完成",
                        "message": result["message"],
                        "redirect_url": redirect_url,
                    },
                )
            except Exception as exc:  # pragma: no cover
                refresh_jobs.emit(job_id, {"status": "error", "stage": "失败", "message": f"城市数据加载失败：{exc}"})

        Thread(target=run_refresh, daemon=True).start()
        return jsonify({"job_id": job_id})

    @app.post("/city/add")
    def add_city_to_library():
        preferences = normalize_preferences(request.form)
        date_text = request.form.get("date") or request.args.get("date") or ""
        city = city_from_search_payload(request.form)
        repository = WeatherRepository()
        repository.add_city_record(
            city,
            province=request.form.get("province", ""),
            country=request.form.get("country", ""),
        )
        flash(f"{city.name} 已加入城市库。", "success")
        return redirect(url_for("city_detail", city_slug=city.slug) + "?" + _query_string(preferences, {"date": date_text}))

    @app.post("/city/delete")
    def delete_city():
        preferences = normalize_preferences(request.form)
        date_text = request.form.get("date") or request.args.get("date") or ""
        city_slug = request.form.get("slug", "").strip()
        city_name = request.form.get("name", "").strip() or "该城市"
        repository = WeatherRepository()
        if repository.delete_city_record(city_slug, purge_cached_data=True):
            flash(f"{city_name} 已从自定义城市库删除。", "success")
        else:
            flash("没有找到需要删除的城市。", "warning")
        return redirect(url_for("home") + "?" + _query_string(preferences, {"date": date_text}))

    @app.get("/api/cities/search")
    def city_search_api():
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"results": []})
        try:
            include_remote = request.args.get("local_only") != "1"
            return jsonify({"results": search_cities(query, include_remote=include_remote)})
        except Exception as exc:
            return jsonify({"results": [], "error": f"城市联想暂时不可用：{exc}"}), 200

    @app.post("/api/assistant")
    def assistant_api():
        payload = request.get_json(silent=True) or {}
        message = str(payload.get("message", "")).strip()
        if not message:
            return jsonify({"answer": "请输入你想了解的问题，例如：今天推荐哪个城市？北京空气质量怎么样？", "mode": "local"})
        repository = WeatherRepository()
        preferences = normalize_preferences(payload.get("preferences") or {})
        result = answer_assistant_message(message, repository, preferences)
        return jsonify(result)
