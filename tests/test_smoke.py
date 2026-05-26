from pathlib import Path
import sys
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app
from config.cities import CityConfig
from config.pinyin import city_name_to_pinyin
from config.preferences import DEFAULT_PREFERENCES
from service.city_search import city_from_search_payload
from service.city_search import search_cities
from service.clean_data import build_forecast_dataset, build_history_daily_dataset, build_history_monthly_dataset
from crawler.forecast_crawler import fetch_forecast_page
from service.database import _sanitize_refresh_message
from service import database
from service.ml_predictor import TravelSuitabilityKnnModel, WeatherKnnForecastModel
from service import pipeline
from service.ranking import _build_homepage_context_cached, build_homepage_context
from service.refresh_progress import RefreshJobStore
from service.scoring import build_weights
from web.routes import _resolve_history_month


class AppSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app.test_client()

    def test_core_pages(self) -> None:
        for path in ["/", "/preferences", "/city/beijing", "/compare", "/history"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)

    def test_assistant_api_returns_local_answer(self) -> None:
        response = self.client.post("/api/assistant", json={"message": "今天推荐哪个城市"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("answer", response.get_json())

    def test_history_month_defaults_to_current_month(self) -> None:
        self.assertEqual(_resolve_history_month(None, list(range(1, 13))), date.today().month)
        self.assertEqual(_resolve_history_month("8", list(range(1, 13))), 8)


class AqiIntegrationTest(unittest.TestCase):
    def test_forecast_cleaning_merges_aqi_by_city_and_date(self) -> None:
        page_payloads = {
            "beijing": {
                "records": [
                    {
                        "city_slug": "beijing",
                        "city_name": "北京",
                        "date": "2026-05-13",
                        "weather_detail": "晴",
                        "max_temp": 28,
                        "min_temp": 18,
                        "avg_temp": 23,
                        "wind_direction": "北风",
                    }
                ]
            }
        }
        api_payloads = {
            "beijing": {
                "records": [
                    {
                        "city_slug": "beijing",
                        "city_name": "北京",
                        "date": "2026-05-13",
                        "precipitation_mm": 0,
                        "wind_speed_kmh": 12,
                        "wind_level": 3,
                    }
                ]
            }
        }
        aqi_payloads = {"beijing": {"records": [{"date": "2026-05-13", "aqi": 86}]}}

        df = build_forecast_dataset(page_payloads, api_payloads, "2026-05-13T10:00:00", aqi_payloads)

        self.assertEqual(len(df), 1)
        self.assertEqual(float(df.iloc[0]["aqi"]), 86.0)

    def test_aqi_weight_is_enabled_and_normalized(self) -> None:
        preferences = {
            "rain_sensitivity": "medium",
            "temperature_preference": "mild",
            "wind_sensitivity": "medium",
            "travel_style": "general",
            "aqi_sensitivity": "medium",
        }

        weights = build_weights(preferences, aqi_available=True)

        self.assertIn("aqi", weights)
        self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_scoring_accepts_nan_wind_level(self) -> None:
        import math

        from service.scoring import score_wind

        score = score_wind({"wind_level": math.nan, "wind_speed_kmh": math.nan}, "medium", "general")

        self.assertEqual(score, 100.0)


class SearchAndModelTest(unittest.TestCase):
    def test_city_payload_builds_dynamic_city(self) -> None:
        city = city_from_search_payload(
            {
                "slug": "geo-1809858",
                "name": "广州",
                "latitude": "23.11667",
                "longitude": "113.25",
            }
        )

        self.assertEqual(city.slug, "geo-1809858")
        self.assertEqual(city.name, "广州")
        self.assertEqual(city.pinyin, "guangzhou")

    def test_city_name_to_pinyin_handles_new_admin_city(self) -> None:
        self.assertEqual(city_name_to_pinyin("哈尔滨"), "haerbin")

    def test_added_city_record_is_persisted(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                _build_homepage_context_cached.cache_clear()
                repo = database.WeatherRepository()
                city = CityConfig("geo-1809858", "广州", "guangzhou", 23.11667, 113.25)

                repo.add_city_record(city, province="广东", country="中国")
                added = repo.get_added_cities()
                added_by_slug = {item["slug"]: item for item in added}

                self.assertEqual(added_by_slug["geo-1809858"]["name"], "广州")
            finally:
                database.DB_PATH = original_db_path

    def test_default_cities_seed_into_editable_city_library(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                repo = database.WeatherRepository()
                names = [item["name"] for item in repo.get_added_cities()]

                self.assertIn("北京", names)
                self.assertIn("三亚", names)
            finally:
                database.DB_PATH = original_db_path

    def test_delete_added_city_removes_record_and_cached_data(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                repo = database.WeatherRepository()
                city = CityConfig("geo-1809858", "广州", "guangzhou", 23.11667, 113.25)
                repo.add_city_record(city, province="广东", country="中国")
                connection = database.get_connection()
                try:
                    connection.execute(
                        "INSERT INTO forecast_daily (city_slug, city_name, date) VALUES (?, ?, ?)",
                        (city.slug, city.name, "2026-05-24"),
                    )
                    connection.execute(
                        "INSERT INTO history_monthly (city_slug, city_name, month_key, month_num) VALUES (?, ?, ?, ?)",
                        (city.slug, city.name, "2026-05", 5),
                    )
                    connection.execute(
                        "INSERT INTO history_daily (city_slug, city_name, date) VALUES (?, ?, ?)",
                        (city.slug, city.name, "2026-05-01"),
                    )
                    connection.commit()
                finally:
                    connection.close()

                deleted = repo.delete_added_city(city.slug)

                self.assertTrue(deleted)
                self.assertNotIn(city.slug, [item["slug"] for item in repo.get_added_cities()])
                self.assertTrue(repo.get_city_forecast(city.slug).empty)
                self.assertTrue(repo.get_history_monthly(city.slug).empty)
                self.assertTrue(repo.get_history_daily(city.slug).empty)
            finally:
                database.DB_PATH = original_db_path

    def test_homepage_city_catalog_reads_editable_city_library(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                repo = database.WeatherRepository()
                city = CityConfig("geo-1809858", "广州", "guangzhou", 23.11667, 113.25)

                repo.add_city_record(city, province="广东", country="中国")
                context = build_homepage_context(repo, "2026-05-24", DEFAULT_PREFERENCES)
                names = [item["name"] for item in context["city_catalog"]]

                self.assertIn("北京", names)
                self.assertIn("广州", names)
                self.assertTrue(all(item["is_custom"] for item in context["city_catalog"]))
            finally:
                _build_homepage_context_cached.cache_clear()
                database.DB_PATH = original_db_path

    def test_city_search_suggests_local_admin_matches_for_single_character(self) -> None:
        class FailingClient:
            def get_json(self, _url):
                raise RuntimeError("network unavailable")

        results = search_cities("广", client=FailingClient())
        names = [item["name"] for item in results]

        self.assertIn("广州", names)
        self.assertIn("广陵", names)

    def test_city_search_shows_hierarchical_location_for_counties(self) -> None:
        results = search_cities("玉田", include_remote=False)
        yutian = next(item for item in results if item["name"] == "玉田")

        self.assertEqual(yutian["display_name"], "中国·河北省·唐山市·玉田县")

    def test_city_search_keeps_same_name_places_separate_by_location(self) -> None:
        results = search_cities("鼓楼", include_remote=False)
        locations = {item["display_name"] for item in results if item["name"] == "鼓楼"}

        self.assertGreaterEqual(len(locations), 2)

    def test_city_search_can_skip_remote_lookup_for_suggestions(self) -> None:
        class FailingClient:
            def get_json(self, _url):
                raise RuntimeError("remote search should not run")

        results = search_cities("广陵", client=FailingClient(), include_remote=False)

        self.assertEqual(results[0]["name"], "广陵")
        self.assertIn("江苏省·扬州市·广陵区", results[0]["display_name"])

    def test_city_search_does_not_show_builtin_city_source(self) -> None:
        results = search_cities("三亚", include_remote=False)

        self.assertTrue(results)
        self.assertTrue(all("内置城市" not in item["display_name"] for item in results))

    def test_city_search_api_returns_json_results(self) -> None:
        with mock.patch("web.routes.search_cities", return_value=[{"name": "广州", "slug": "geo-1809858"}]):
            response = app.test_client().get("/api/cities/search?q=广")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"][0]["name"], "广州")

    def test_city_search_api_supports_local_only_suggestions(self) -> None:
        with mock.patch("web.routes.search_cities", return_value=[]) as mocked_search:
            response = app.test_client().get("/api/cities/search?q=广&local_only=1")

        self.assertEqual(response.status_code, 200)
        mocked_search.assert_called_once_with("广", include_remote=False)

    def test_selected_search_city_shows_preview_without_saving_city(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                preview = {
                    "forecast": {
                        "date": "2026-05-24",
                        "weather_detail": "晴",
                        "avg_temp": 23.0,
                        "precipitation_mm": 0.0,
                        "wind_level": 2,
                    },
                    "errors": [],
                }
                with mock.patch("web.routes.preview_city_forecast", return_value=preview), \
                    mock.patch("web.routes.refresh_city_data") as mocked_refresh:
                    response = app.test_client().get(
                        "/?q=玉田&candidate_slug=cn-130229&candidate_name=玉田&candidate_latitude=39.818843"
                        "&candidate_longitude=117.734753&candidate_province=河北省&candidate_country=中国"
                        "&candidate_display_name=中国·河北省·唐山市·玉田县"
                    )

                self.assertEqual(response.status_code, 200)
                text = response.data.decode("utf-8")
                self.assertIn("中国·河北省·唐山市·玉田县", text)
                self.assertIn("当前天气", text)
                self.assertIn("查看详情", text)
                self.assertNotIn("添加城市</button>", text)
                mocked_refresh.assert_not_called()
                self.assertNotIn("cn-130229", [item["slug"] for item in database.WeatherRepository().get_added_cities()])
            finally:
                database.DB_PATH = original_db_path

    def test_refresh_city_redirects_to_detail_with_selected_date(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                with mock.patch("web.routes.refresh_city_data", return_value={"errors": [], "message": "ok"}):
                    response = app.test_client().post(
                        "/city/refresh",
                        data={
                            "slug": "geo-1809858",
                            "name": "广州",
                            "latitude": "23.11667",
                            "longitude": "113.25",
                            "province": "广东",
                            "country": "中国",
                            "date": "2026-05-24",
                            **DEFAULT_PREFERENCES,
                        },
                    )

                self.assertEqual(response.status_code, 302)
                self.assertIn("/city/geo-1809858", response.headers["Location"])
                self.assertIn("date=2026-05-24", response.headers["Location"])
            finally:
                database.DB_PATH = original_db_path

    def test_refresh_city_start_builds_redirect_outside_request_context(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                captured = {}
                job_store = RefreshJobStore()

                class DelayedThread:
                    def __init__(self, target, daemon=False):
                        captured["target"] = target

                    def start(self):
                        pass

                with mock.patch("web.routes.refresh_jobs", job_store), \
                    mock.patch("web.routes.Thread", DelayedThread), \
                    mock.patch("web.routes.refresh_city_data", return_value={"errors": [], "message": "ok"}):
                    response = app.test_client().post(
                        "/city/refresh/start",
                        data={
                            "slug": "cn-440300",
                            "name": "深圳",
                            "latitude": "22.546054",
                            "longitude": "114.025974",
                            "province": "广东省",
                            "country": "中国",
                            "date": "2026-05-31",
                            **DEFAULT_PREFERENCES,
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    job_id = response.get_json()["job_id"]
                    captured["target"]()
                    events = list(job_store.listen(job_id, timeout=0.01))

                self.assertEqual(events[-1]["status"], "done")
                self.assertIn("/city/cn-440300", events[-1]["redirect_url"])
                self.assertIn("name=%E6%B7%B1%E5%9C%B3", events[-1]["redirect_url"])
                self.assertIn("latitude=22.546054", events[-1]["redirect_url"])
                self.assertNotIn("Working outside", events[-1]["message"])
                self.assertNotIn("cn-440300", [item["slug"] for item in database.WeatherRepository().get_added_cities()])
            finally:
                database.DB_PATH = original_db_path

    def test_add_city_to_library_requires_explicit_detail_action(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                response = app.test_client().post(
                    "/city/add",
                    data={
                        "slug": "cn-440300",
                        "name": "深圳",
                        "latitude": "22.546054",
                        "longitude": "114.025974",
                        "province": "广东省",
                        "country": "中国",
                        "date": "2026-05-31",
                        **DEFAULT_PREFERENCES,
                    },
                )

                self.assertEqual(response.status_code, 302)
                self.assertIn("/city/cn-440300", response.headers["Location"])
                self.assertIn("date=2026-05-31", response.headers["Location"])
                self.assertIn("cn-440300", [item["slug"] for item in database.WeatherRepository().get_added_cities()])
            finally:
                database.DB_PATH = original_db_path

    def test_home_search_history_items_can_be_deleted(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                repo = database.WeatherRepository()
                city = CityConfig("geo-test-history", "测试城", "ceshicheng", 31.2, 121.5)
                repo.add_city_record(city, province="测试省", country="中国")
                repo.add_search_history(city, province="测试省", country="中国")

                response = app.test_client().get("/")

                self.assertEqual(response.status_code, 200)
                text = response.data.decode("utf-8")
                self.assertIn("搜索历史", text)
                self.assertIn("/search-history/delete", text)
                self.assertIn('aria-label="删除 测试城"', text)
                self.assertIn('class="history-city-delete"', text)
            finally:
                database.DB_PATH = original_db_path

    def test_city_detail_query_records_search_history_without_adding_city(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                with mock.patch("web.routes.build_city_detail_context", return_value={}):
                    response = app.test_client().get(
                        "/city/cn-440300?name=深圳&latitude=22.546054&longitude=114.025974"
                        "&province=广东省&country=中国&date=2026-05-31"
                    )

                self.assertEqual(response.status_code, 200)
                repo = database.WeatherRepository()
                self.assertIn("cn-440300", [item["slug"] for item in repo.get_search_history()])
                self.assertNotIn("cn-440300", [item["slug"] for item in repo.get_added_cities()])
            finally:
                database.DB_PATH = original_db_path

    def test_delete_search_history_does_not_remove_city_library_entry(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                repo = database.WeatherRepository()
                city = CityConfig("geo-test-history", "测试城", "ceshicheng", 31.2, 121.5)
                repo.add_city_record(city, province="测试省", country="中国")
                repo.add_search_history(city, province="测试省", country="中国")

                response = app.test_client().post(
                    "/search-history/delete",
                    data={"slug": city.slug, "name": city.name, "date": "2026-05-31", **DEFAULT_PREFERENCES},
                )

                self.assertEqual(response.status_code, 302)
                self.assertNotIn(city.slug, [item["slug"] for item in repo.get_search_history()])
                self.assertIn(city.slug, [item["slug"] for item in repo.get_added_cities()])
            finally:
                database.DB_PATH = original_db_path

    def test_delete_city_route_removes_custom_city(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                repo = database.WeatherRepository()
                city = CityConfig("geo-1809858", "广州", "guangzhou", 23.11667, 113.25)
                repo.add_city_record(city, province="广东", country="中国")

                response = app.test_client().post(
                    "/city/delete",
                    data={"slug": city.slug, "name": city.name, "date": "2026-05-24", **DEFAULT_PREFERENCES},
                )

                self.assertEqual(response.status_code, 302)
                self.assertIn("date=2026-05-24", response.headers["Location"])
                self.assertNotIn(city.slug, [item["slug"] for item in repo.get_added_cities()])
            finally:
                database.DB_PATH = original_db_path

    def test_delete_city_route_can_remove_seeded_default_city(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                repo = database.WeatherRepository()
                response = app.test_client().post(
                    "/city/delete",
                    data={"slug": "beijing", "name": "北京", "date": "2026-05-24", **DEFAULT_PREFERENCES},
                )

                self.assertEqual(response.status_code, 302)
                self.assertIn("date=2026-05-24", response.headers["Location"])
                self.assertNotIn("beijing", [item["slug"] for item in repo.get_added_cities()])
                detail_response = app.test_client().get("/city/beijing")
                self.assertEqual(detail_response.status_code, 302)
            finally:
                database.DB_PATH = original_db_path

    def test_knn_model_predicts_score(self) -> None:
        import pandas as pd

        history_df = pd.DataFrame(
            [
                {
                    "month_num": 5,
                    "avg_temp": 22,
                    "rainy_ratio": 0.2,
                    "comfortable_days_ratio": 0.8,
                    "temp_std": 3,
                    "avg_wind_speed_kmh": 12,
                },
                {
                    "month_num": 8,
                    "avg_temp": 31,
                    "rainy_ratio": 0.6,
                    "comfortable_days_ratio": 0.2,
                    "temp_std": 8,
                    "avg_wind_speed_kmh": 20,
                },
            ]
        )
        model = TravelSuitabilityKnnModel(history_df, neighbors=1)
        prediction = model.predict(
            {
                "month_num": 5,
                "avg_temp": 23,
                "rainy_ratio": 0.2,
                "comfortable_days_ratio": 0.8,
                "temp_std": 3,
                "avg_wind_speed_kmh": 12,
            }
        )

        self.assertIsNotNone(prediction["ml_score"])
        self.assertGreater(prediction["ml_confidence"], 0)

    def test_weather_knn_model_predicts_weather_fields(self) -> None:
        import pandas as pd

        history_df = pd.DataFrame(
            [
                {
                    "city_slug": "xiamen",
                    "city_name": "厦门",
                    "month_num": 5,
                    "avg_temp": 24,
                    "rainy_ratio": 0.3,
                    "temp_std": 3,
                    "avg_wind_speed_kmh": 14,
                },
                {
                    "city_slug": "xiamen",
                    "city_name": "厦门",
                    "month_num": 6,
                    "avg_temp": 27,
                    "rainy_ratio": 0.5,
                    "temp_std": 4,
                    "avg_wind_speed_kmh": 16,
                },
            ]
        )
        model = WeatherKnnForecastModel(history_df, neighbors=1)
        prediction = model.predict({"city_slug": "xiamen", "city_name": "厦门", "date": "2026-05-25"})

        self.assertIsNotNone(prediction)
        self.assertEqual(prediction["city_name"], "厦门")
        self.assertIn("avg_temp", prediction)
        self.assertIn("rain_probability", prediction)
        self.assertIn("wind_speed_kmh", prediction)
        self.assertGreater(prediction["confidence"], 0)

    def test_weather_knn_ignores_forecast_temperature_input(self) -> None:
        import pandas as pd

        history_df = pd.DataFrame(
            [
                {
                    "city_slug": "nanjing",
                    "city_name": "南京",
                    "month_num": 5,
                    "avg_temp": 22,
                    "rainy_ratio": 0.2,
                    "temp_std": 3,
                    "avg_wind_speed_kmh": 12,
                }
            ]
        )
        model = WeatherKnnForecastModel(history_df, neighbors=1)
        cool_day = model.predict({"city_slug": "nanjing", "city_name": "南京", "date": "2026-05-24", "avg_temp": 10})
        warm_day = model.predict({"city_slug": "nanjing", "city_name": "南京", "date": "2026-05-24", "avg_temp": 35})

        self.assertEqual(cool_day["avg_temp"], warm_day["avg_temp"])

    def test_weather_knn_uses_recent_daily_trend(self) -> None:
        import pandas as pd

        dates = pd.date_range("2026-02-15", periods=75)
        daily_df = pd.DataFrame(
            [
                {
                    "city_slug": "nanjing",
                    "city_name": "南京",
                    "date": day.strftime("%Y-%m-%d"),
                    "month_num": day.month,
                    "day_of_year": day.dayofyear,
                    "max_temp": 18 + index * 0.12 + 5,
                    "min_temp": 18 + index * 0.12 - 5,
                    "avg_temp": 18 + index * 0.12,
                    "rain_flag": 1 if index % 8 == 0 else 0,
                    "precipitation_mm": 1.0 if index % 8 == 0 else 0.0,
                    "wind_speed_kmh": 12,
                }
                for index, day in enumerate(dates)
            ]
        )
        model = WeatherKnnForecastModel(daily_df, neighbors=5)
        prediction = model.predict({"city_slug": "nanjing", "city_name": "南京", "date": "2026-05-10"})

        self.assertGreater(prediction["avg_temp"], 23.0)

    def test_history_daily_dataset_keeps_daily_training_rows(self) -> None:
        payloads = {
            "beijing": {
                "records": [
                    {
                        "city_slug": "beijing",
                        "city_name": "北京",
                        "date": "2026-05-01",
                        "max_temp": 27,
                        "min_temp": 17,
                        "avg_temp": 22,
                        "weather_detail": "晴",
                        "precipitation_mm": 0,
                        "wind_speed_kmh": 10,
                    }
                ]
            }
        }

        df = build_history_daily_dataset(payloads, "2026-05-24T16:00:00")

        self.assertEqual(len(df), 1)
        self.assertEqual(int(df.iloc[0]["month_num"]), 5)
        self.assertEqual(int(df.iloc[0]["rain_flag"]), 0)

    def test_history_monthly_uses_adaptive_city_month_comfort(self) -> None:
        payloads = {
            "beijing": {
                "records": [
                    {
                        "city_slug": "beijing",
                        "city_name": "北京",
                        "date": f"2026-01-{day:02d}",
                        "max_temp": avg_temp + 4,
                        "min_temp": avg_temp - 4,
                        "avg_temp": avg_temp,
                        "precipitation_mm": 0,
                        "wind_speed_kmh": 10,
                    }
                    for day, avg_temp in enumerate([-10, -5, 1, 4, 9], start=1)
                ]
            }
        }

        df = build_history_monthly_dataset(payloads, "2026-05-26T10:00:00")
        ratio = float(df.iloc[0]["comfortable_days_ratio"])

        self.assertGreater(ratio, 0.0)
        self.assertLess(ratio, 1.0)


class RefreshProgressTest(unittest.TestCase):
    def test_refresh_job_store_streams_until_done(self) -> None:
        store = RefreshJobStore()
        job_id = store.create()
        store.emit(job_id, {"status": "running", "message": "正在抓取北京天气"})
        store.emit(job_id, {"status": "done", "message": "刷新完成"})

        events = list(store.listen(job_id, timeout=0.1))

        self.assertEqual(events[0]["status"], "running")
        self.assertEqual(events[-1]["status"], "done")

    def test_forecast_page_failure_uses_api_fallback_without_raw_error(self) -> None:
        city = CityConfig("beijing", "北京", "beijing", 39.9042, 116.4074)
        api_payload = {
            "records": [
                {
                    "city_slug": "beijing",
                    "city_name": "北京",
                    "date": "2026-05-24",
                    "max_temp_api": 28,
                    "min_temp_api": 18,
                    "avg_temp_api": 23,
                    "weather_type_api": "clear",
                    "weather_detail_api": "晴",
                    "wind_speed_kmh": 10,
                    "wind_level": 2,
                    "precipitation_mm": 0,
                }
            ]
        }
        aqi_payload = {"records": [{"date": "2026-05-24", "aqi": 50}]}
        history_payload = {
            "records": [
                {
                    "city_slug": "beijing",
                    "city_name": "北京",
                    "date": "2026-05-01",
                    "precipitation_mm": 0,
                    "avg_temp": 22,
                    "max_temp": 27,
                    "min_temp": 17,
                    "wind_speed_kmh": 10,
                }
            ]
        }

        with mock.patch.object(pipeline, "_refresh_city_list", return_value=[city]), \
            mock.patch.object(pipeline, "to_iso_timestamp", return_value="2026-05-24T16:00:00"), \
            mock.patch.object(pipeline, "fetch_forecast_page", side_effect=RuntimeError("HTTPSConnectionPool raw ssl failure")), \
            mock.patch.object(pipeline, "fetch_forecast_api", return_value=api_payload), \
            mock.patch.object(pipeline, "fetch_air_quality_api", return_value=aqi_payload), \
            mock.patch.object(pipeline, "fetch_history_daily", return_value=history_payload), \
            mock.patch.object(pipeline, "_forecast_cache_is_current", return_value=False), \
            mock.patch.object(pipeline, "_aqi_cache_is_current", return_value=False), \
            mock.patch.object(pipeline, "_history_cache_is_current", return_value=False), \
            mock.patch.object(pipeline, "_save_json"), \
            mock.patch.object(pipeline, "save_processed_artifacts"), \
            mock.patch.object(pipeline, "write_dataframe"), \
            mock.patch.object(pipeline, "write_city_dataframe"), \
            mock.patch.object(pipeline, "log_refresh"):
            result = pipeline.refresh_all_data()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["errors"], [])
        self.assertIn("Open-Meteo API 兜底", result["message"])
        self.assertNotIn("HTTPSConnectionPool", result["message"])

    def test_refresh_all_data_uses_editable_city_library(self) -> None:
        added_city = CityConfig("geo-1809858", "广州", "guangzhou", 23.11667, 113.25)
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                repo = database.WeatherRepository()
                repo.add_city_record(added_city, province="广东", country="中国")

                calls = []

                def fake_forecast_api(city, client=None):
                    calls.append(city.slug)
                    return {"records": []}

                with mock.patch.object(pipeline, "to_iso_timestamp", return_value="2026-05-24T16:00:00"), \
                    mock.patch.object(pipeline, "fetch_forecast_page", return_value={"records": []}), \
                    mock.patch.object(pipeline, "fetch_forecast_api", side_effect=fake_forecast_api), \
                    mock.patch.object(pipeline, "fetch_air_quality_api", return_value={"records": []}), \
                    mock.patch.object(pipeline, "_history_cache_is_current", return_value=True), \
                    mock.patch.object(pipeline, "_save_json"), \
                    mock.patch.object(pipeline, "save_processed_artifacts"), \
                    mock.patch.object(pipeline, "write_dataframe"), \
                    mock.patch.object(pipeline, "write_city_dataframe"), \
                    mock.patch.object(pipeline, "log_refresh"):
                    pipeline.refresh_all_data()

                self.assertIn("beijing", calls)
                self.assertIn("geo-1809858", calls)
            finally:
                database.DB_PATH = original_db_path

    def test_refresh_message_hides_raw_client_error_url(self) -> None:
        raw_message = (
            "未来天气 70 条，AQI 50 条，历史月度统计 576 条，历史日样本 17514 条。 "
            "历史数据抓取失败: 三亚 -> 429 Client Error: Too Many Requests for url: "
            "https://archive-api.open-meteo.com/v1/archive?latitude=18.25&longitude=109.51"
        )

        cleaned = _sanitize_refresh_message(raw_message)

        self.assertIn("历史数据暂时不可用：三亚 请求过于频繁", cleaned)
        self.assertNotIn("Client Error", cleaned)
        self.assertNotIn("https://", cleaned)

    def test_friendly_fetch_error_hides_exception_details(self) -> None:
        message = pipeline._friendly_fetch_error(
            "历史数据",
            "三亚",
            RuntimeError("429 Client Error: Too Many Requests for url: https://example.test/raw"),
        )

        self.assertEqual(message, "历史数据暂时不可用：三亚 请求过于频繁，本次未更新，请稍后重试。")

    def test_friendly_fetch_error_identifies_gateway_failure(self) -> None:
        message = pipeline._friendly_fetch_error(
            "未来天气补充数据",
            "广州",
            RuntimeError("502 Server Error: Bad Gateway for url: https://example.test/raw"),
        )

        self.assertIn("上游天气服务暂时不可用", message)

    def test_forecast_page_uses_tianqi_alias_for_search_city(self) -> None:
        class AliasClient:
            def __init__(self) -> None:
                self.urls = []

            def get_text(self, url: str) -> str:
                self.urls.append(url)
                if "guangzhou" not in url:
                    raise RuntimeError("not found")
                return """
                <div class="day7 hide twty_hour">
                    <ul class="week"><li><b>05月26日</b></li></ul>
                    <ul class="txt txt2"><li>晴</li></ul>
                    <div class="zxt_shuju"><ul><li><span>35</span><b>28</b></li></ul></div>
                    <ul class="txt"><li>南风</li></ul>
                </div>
                """

        city = CityConfig("geo-1809858", "广州", "geo-1809858", 23.11667, 113.25)
        client = AliasClient()

        payload = fetch_forecast_page(city, client=client)

        self.assertEqual(len(payload["records"]), 1)
        self.assertTrue(any("guangzhou" in url for url in client.urls))
        self.assertTrue(all("geo-1809858" not in url for url in client.urls))
        self.assertEqual(payload["records"][0]["weather_detail"], "晴")

    def test_history_cache_current_when_covered_to_last_month(self) -> None:
        repository = mock.Mock()
        repository.get_history_daily_coverage.return_value = {
            "row_count": 1200,
            "start_date": "2021-01-01",
            "end_date": "2026-04-30",
        }

        with mock.patch.object(
            pipeline,
            "default_history_range",
            return_value=(date(2021, 1, 1), date(2026, 4, 30)),
        ):
            is_current = pipeline._history_cache_is_current(repository, "sanya")

        self.assertTrue(is_current)

    def test_history_cache_stale_when_last_month_missing(self) -> None:
        repository = mock.Mock()
        repository.get_history_daily_coverage.return_value = {
            "row_count": 1200,
            "start_date": "2021-01-01",
            "end_date": "2026-03-31",
        }

        with mock.patch.object(
            pipeline,
            "default_history_range",
            return_value=(date(2021, 1, 1), date(2026, 4, 30)),
        ):
            is_current = pipeline._history_cache_is_current(repository, "sanya")

        self.assertFalse(is_current)

    def test_refresh_city_reuses_current_forecast_and_aqi_cache(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                repo = database.WeatherRepository()
                city = CityConfig("geo-1809858", "广州", "guangzhou", 23.11667, 113.25)
                repo.add_city_record(city, province="广东", country="中国")
                today = date.today()
                connection = database.get_connection()
                try:
                    for offset in range(5):
                        connection.execute(
                            """
                            INSERT INTO forecast_daily
                                (city_slug, city_name, date, aqi, crawl_time)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                city.slug,
                                city.name,
                                (today + timedelta(days=offset)).isoformat(),
                                50 + offset,
                                f"{today.isoformat()}T08:00:00",
                            ),
                        )
                    connection.commit()
                finally:
                    connection.close()

                with mock.patch.object(pipeline, "fetch_forecast_api") as mocked_forecast, \
                    mock.patch.object(pipeline, "fetch_air_quality_api") as mocked_aqi, \
                    mock.patch.object(pipeline, "_history_cache_is_current", return_value=True), \
                    mock.patch.object(pipeline, "fetch_history_daily"):
                    result = pipeline.refresh_city_data(city)

                mocked_forecast.assert_not_called()
                mocked_aqi.assert_not_called()
                self.assertEqual(result["forecast_rows"], 5)
                self.assertEqual(result["aqi_rows"], 5)
                self.assertIn("复用今日缓存", result["message"])
            finally:
                database.DB_PATH = original_db_path

    def test_refresh_city_keeps_page_forecast_when_api_gateway_fails(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                city = CityConfig("geo-1809858", "广州", "geo-1809858", 23.11667, 113.25)
                page_payload = {
                    "records": [
                        {
                            "city_slug": city.slug,
                            "city_name": city.name,
                            "date": "2026-05-26",
                            "weather_detail": "晴",
                            "weather_type": "晴",
                            "max_temp": 35,
                            "min_temp": 28,
                            "avg_temp": 31.5,
                            "wind_direction": "南风",
                        }
                    ]
                }
                aqi_payload = {"records": [{"date": "2026-05-26", "aqi": 80}]}

                with mock.patch.object(pipeline, "fetch_forecast_page", return_value=page_payload), \
                    mock.patch.object(pipeline, "fetch_forecast_api", side_effect=RuntimeError("502 Server Error: Bad Gateway")), \
                    mock.patch.object(pipeline, "fetch_air_quality_api", return_value=aqi_payload), \
                    mock.patch.object(pipeline, "_history_cache_is_current", return_value=True), \
                    mock.patch.object(pipeline, "_save_json"):
                    result = pipeline.refresh_city_data(city)

                self.assertEqual(result["errors"], [])
                self.assertEqual(result["forecast_rows"], 1)
                self.assertEqual(result["aqi_rows"], 1)
                self.assertFalse(database.WeatherRepository().get_city_forecast(city.slug).empty)
            finally:
                database.DB_PATH = original_db_path

    def test_prune_data_for_removed_cities_drops_stale_cache(self) -> None:
        original_db_path = database.DB_PATH
        with tempfile.TemporaryDirectory() as temp_dir:
            database.DB_PATH = Path(temp_dir) / "test.sqlite3"
            try:
                repo = database.WeatherRepository()
                connection = database.get_connection()
                try:
                    connection.execute(
                        "INSERT INTO forecast_daily (city_slug, city_name, date) VALUES (?, ?, ?)",
                        ("geo-removed", "已删城市", "2026-05-24"),
                    )
                    connection.execute(
                        "INSERT INTO history_monthly (city_slug, city_name, month_key, month_num) VALUES (?, ?, ?, ?)",
                        ("geo-removed", "已删城市", "2026-05", 5),
                    )
                    connection.execute(
                        "INSERT INTO history_daily (city_slug, city_name, date) VALUES (?, ?, ?)",
                        ("geo-removed", "已删城市", "2026-05-01"),
                    )
                    connection.commit()
                finally:
                    connection.close()

                deleted = repo.prune_data_for_removed_cities()

                self.assertEqual(deleted, 3)
                self.assertTrue(repo.get_city_forecast("geo-removed").empty)
                self.assertTrue(repo.get_history_monthly("geo-removed").empty)
                self.assertTrue(repo.get_history_daily("geo-removed").empty)
            finally:
                database.DB_PATH = original_db_path


if __name__ == "__main__":
    unittest.main()
