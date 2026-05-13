from pathlib import Path
import sys
import unittest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app
from service.clean_data import build_forecast_dataset
from service.scoring import build_weights


class AppSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app.test_client()

    def test_core_pages(self) -> None:
        for path in ["/", "/preferences", "/city/beijing", "/compare", "/history"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)


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


if __name__ == "__main__":
    unittest.main()
