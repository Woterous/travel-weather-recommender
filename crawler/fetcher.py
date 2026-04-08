from __future__ import annotations

import requests

from config.sources import REQUEST_HEADERS, REQUEST_TIMEOUT


class HttpClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(REQUEST_HEADERS)

    def get_text(self, url: str) -> str:
        response = self.session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.text

    def get_json(self, url: str) -> dict:
        response = self.session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
