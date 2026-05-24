from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app
from config.cities import CityConfig
from service.city_search import city_from_search_payload
from service.clean_data import build_forecast_dataset
from service.ml_predictor import TravelSuitabilityKnnModel, WeatherKnnForecastModel
from service import pipeline
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

    def test_weather_knn_uses_api_trend_context(self) -> None:
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
        context = {"api_avg_temp_mean": 25}
        cool_day = model.predict(
            {"city_slug": "nanjing", "city_name": "南京", "date": "2026-05-24", "avg_temp": 23},
            series_context=context,
        )
        warm_day = model.predict(
            {"city_slug": "nanjing", "city_name": "南京", "date": "2026-05-25", "avg_temp": 29},
            series_context=context,
        )

        self.assertLess(cool_day["avg_temp"], warm_day["avg_temp"])

    def test_weather_knn_keeps_short_term_temperature_close_to_api(self) -> None:
        import pandas as pd

        history_df = pd.DataFrame(
            [
                {
                    "city_slug": "nanjing",
                    "city_name": "南京",
                    "month_num": 5,
                    "avg_temp": 21.5,
                    "rainy_ratio": 0.35,
                    "temp_std": 3,
                    "avg_wind_speed_kmh": 16,
                }
            ]
        )
        model = WeatherKnnForecastModel(history_df, neighbors=1)
        prediction = model.predict(
            {"city_slug": "nanjing", "city_name": "南京", "date": "2026-05-30", "avg_temp": 26.0},
            series_context={"api_avg_temp_mean": 25.5},
        )

        self.assertGreaterEqual(prediction["avg_temp"], 25.0)


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
            mock.patch.object(pipeline, "_save_json"), \
            mock.patch.object(pipeline, "save_processed_artifacts"), \
            mock.patch.object(pipeline, "write_dataframe"), \
            mock.patch.object(pipeline, "log_refresh"):
            result = pipeline.refresh_all_data()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["errors"], [])
        self.assertIn("Open-Meteo API 兜底", result["message"])
        self.assertNotIn("HTTPSConnectionPool", result["message"])


if __name__ == "__main__":
    unittest.main()
