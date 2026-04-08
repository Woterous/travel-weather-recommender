from pathlib import Path
import sys
import unittest


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app


class AppSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app.test_client()

    def test_core_pages(self) -> None:
        for path in ["/", "/preferences", "/city/beijing", "/compare", "/history"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)


if __name__ == "__main__":
    unittest.main()
