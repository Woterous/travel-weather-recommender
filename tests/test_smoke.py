from pathlib import Path
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app
from config.cities import CityConfig
from config.preferences import DEFAULT_PREFERENCES
from service.city_search import city_from_search_payload
from service.city_search import search_cities
from service.clean_data import build_forecast_dataset, build_history_daily_dataset
from service.database import _sanitize_refresh_message
from service import database
from service.ml_predictor import TravelSuitabilityKnnModel, WeatherKnnForecastModel
from service import pipeline
from service.ranking import _build_homepage_context_cached, build_homepage_context
from service.refresh_progress import RefreshJobStore
from service.scoring import build_weights


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

                self.assertEqual(added[0]["slug"], "geo-1809858")
                self.assertEqual(added[0]["name"], "广州")
            finally:
                database.DB_PATH = original_db_path

    def test_homepage_city_catalog_includes_default_and_added_cities(self) -> None:
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
            finally:
                _build_homepage_context_cached.cache_clear()
                database.DB_PATH = original_db_path

    def test_city_search_suggests_curated_matches_for_single_character(self) -> None:
        class FailingClient:
            def get_json(self, _url):
                raise RuntimeError("network unavailable")

        results = search_cities("广", client=FailingClient())
        names = [item["name"] for item in results]

        self.assertIn("广州", names)
        self.assertIn("广陵", names)

    def test_city_search_can_skip_remote_lookup_for_suggestions(self) -> None:
        class FailingClient:
            def get_json(self, _url):
                raise RuntimeError("remote search should not run")

        results = search_cities("广陵", client=FailingClient(), include_remote=False)

        self.assertEqual(results[0]["name"], "广陵")

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

        with mock.patch.object(pipeline, "CITIES", [city]), \
            mock.patch.object(pipeline, "to_iso_timestamp", return_value="2026-05-24T16:00:00"), \
            mock.patch.object(pipeline, "fetch_forecast_page", side_effect=RuntimeError("HTTPSConnectionPool raw ssl failure")), \
            mock.patch.object(pipeline, "fetch_forecast_api", return_value=api_payload), \
            mock.patch.object(pipeline, "fetch_air_quality_api", return_value=aqi_payload), \
            mock.patch.object(pipeline, "fetch_history_daily", return_value=history_payload), \
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


if __name__ == "__main__":
    unittest.main()
