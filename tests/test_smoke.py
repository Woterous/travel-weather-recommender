from pathlib import Path
import sys
import unittest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app
from service.city_search import city_from_search_payload
from service.clean_data import build_forecast_dataset
from service.ml_predictor import TravelSuitabilityKnnModel
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


if __name__ == "__main__":
    unittest.main()
