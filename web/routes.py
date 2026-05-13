from __future__ import annotations

from urllib.parse import urlencode

from flask import Flask, flash, redirect, render_template, request, url_for

from config.cities import CITIES, CITY_BY_SLUG, DEFAULT_CITY_SLUG
from config.preferences import DEFAULT_PREFERENCES, PREFERENCE_OPTIONS, normalize_preferences, preference_label
from service.compare import build_compare_context
from service.database import WeatherRepository
from service.history_analysis import get_city_history_series, get_history_ranking, month_num_options
from service.pipeline import refresh_all_data
from service.ranking import build_city_detail_context, build_homepage_context
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
    return available_dates[0]


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
        }

    @app.get("/")
    def home():
        repository = WeatherRepository()
        dates = repository.get_forecast_dates()
        selected_date = _resolve_selected_date(request.args.get("date"), dates)
        preferences = normalize_preferences(request.args)
        context = (
            build_homepage_context(repository, selected_date, preferences)
            if selected_date
            else {
                "ranking": [],
                "chart_data": {"cities": [], "scores": []},
                "weights_preview": {},
                "aqi_available": False,
            }
        )
        return render_template(
            "index.html",
            selected_date=selected_date,
            available_dates=dates,
            preferences=preferences,
            latest_refresh=repository.get_latest_refresh_info(),
            default_compare_city="shanghai",
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
        context = build_city_detail_context(repository, city_slug, selected_date, preferences) if selected_date else {}
        return render_template(
            "city_detail.html",
            city=CITY_BY_SLUG[city_slug],
            selected_date=selected_date,
            available_dates=dates,
            preferences=preferences,
            latest_refresh=repository.get_latest_refresh_info(),
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
        return render_template(
            "compare.html",
            city_a=city_a,
            city_b=city_b,
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
        result = refresh_all_data()
        if result["errors"]:
            flash(result["message"], "warning")
        else:
            flash("数据刷新完成。", "success")
        preferences = normalize_preferences(request.form or request.args)
        date_text = request.form.get("date") or request.args.get("date") or ""
        return redirect(url_for("home") + "?" + _query_string(preferences, {"date": date_text}))
