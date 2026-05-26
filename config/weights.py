from __future__ import annotations


LITERATURE_BASED_WEIGHTS_WITH_AQI = {
    "temperature": 0.30,
    "rain": 0.22,
    "history": 0.18,
    "wind": 0.10,
    "weather": 0.10,
    "aqi": 0.10,
}


LITERATURE_BASED_WEIGHTS_NO_AQI = {
    "temperature": 0.33,
    "rain": 0.25,
    "history": 0.20,
    "wind": 0.10,
    "weather": 0.12,
}


WEIGHT_BASIS = {
    "temperature": "TCI/HCI both assign the largest share to daytime or perceived thermal comfort.",
    "rain": "TCI and HCI treat precipitation as a core physical constraint on tourism activity.",
    "wind": "TCI and HCI both retain wind as a lower-weight physical comfort factor.",
    "weather": "Weather type is the project proxy for sunshine/cloud/aesthetic conditions.",
    "history": "Historical stability is retained to represent local monthly climate reliability.",
    "aqi": "Air-pollution tourism studies show PM2.5/AQI reduces tourist arrivals and destination experience.",
}
