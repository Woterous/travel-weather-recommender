# Travel Weather Recommender

[中文 README](README.md)

A local web application for travel weather recommendation and visualization. The project uses Flask and SQLite to combine forecast weather, air quality, historical weather, and user preferences, then produces city rankings, city detail pages, city comparison, historical analysis, and a data-grounded assistant.

## Features

- **Home recommendations**: city ranking by selected date and user preferences, with score breakdowns, weather summaries, and ECharts charts.
- **City search and library**: local administrative-code search plus optional Open-Meteo Geocoding lookup; searched cities can be added to the local city library.
- **City detail page**: future weather, score breakdown, machine-learning prediction, and city-level refresh entry.
- **City comparison**: compare two cities under the same date and preference settings.
- **Historical analysis**: monthly stability, comfortable-day ratio, rainy-day ratio, and historical suitability ranking.
- **Preference settings**: rain sensitivity, temperature preference, wind sensitivity, travel style, and AQI sensitivity.
- **Refresh progress**: full refresh and single-city refresh show real-time progress stages.
- **Optional auto refresh**: disabled by default; when enabled, the home page refreshes only if today's data has not been refreshed yet.
- **Local assistant**: answers from the local SQLite data by default, with optional external model integration.

## Tech Stack

- Python 3.13
- Flask
- pandas
- requests + BeautifulSoup4
- pypinyin
- SQLite
- HTML / CSS / JavaScript / ECharts

## Data Sources

The application reads page data from local SQLite by default. During refresh, it collects new data or reuses valid local cache:

- Future weather page data: tianqi.com.
- Future weather API: Open-Meteo Forecast API, used for temperature, precipitation, wind fields, and as a fallback source.
- Air quality: Open-Meteo Air Quality API.
- Historical weather: Open-Meteo Archive API, used for monthly statistics and ML samples.
- City search: local `service/reference/china_admin_geocodes.csv`, with optional Open-Meteo Geocoding API fallback.

Refresh results are written to `data/db/weather_recommender.sqlite3`. Raw JSON and processed CSV files are also kept. If an upstream source fails, the project tries to reuse local cache or fallback API data and records the status in the refresh log.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open:

```text
http://127.0.0.1:5000/
```

## Data Refresh

### In the Web UI

- The home page refresh button starts a full refresh.
- Search results and city detail pages can refresh one city only.
- The progress modal shows the current stage, progress, and next step.

### From the Command Line

```powershell
python scripts/crawl_all.py
```

or:

```powershell
python scripts/build_processed_data.py
```

Both scripts call the same `refresh_all_data()` pipeline and update SQLite, raw JSON, and processed CSV files.

### Auto Refresh Switch

Auto refresh is disabled by default. To enable it, edit `config/refresh.py`:

```python
AUTO_REFRESH_ON_HOME_OPEN = 0  # disabled by default
AUTO_REFRESH_ON_HOME_OPEN = 1  # enable stale-data refresh on home page open
```

When enabled, the home page triggers a refresh only if the latest successful or partially successful refresh record is not from today. If today's data is already current, no external requests are made.

## Machine Learning and Scoring

The system first scores travel suitability with rule-based weights. It then trains a lightweight KNN predictor from historical daily weather samples, predicts future weather fields, and scores the predicted weather again. The UI compares:

- API-based future weather score.
- ML-predicted weather fields.
- Score generated from the ML-predicted weather.
- Prediction confidence and sample count.

User preferences change the scoring weights. If AQI is unavailable, the weights are adjusted automatically. See `docs/aqi-and-weight-basis.md` for the scoring basis.

## Assistant Configuration

By default, the assistant answers from local SQLite data and does not require an external API key. To enable an external model, configure environment variables or `config/local_ai.json`:

```powershell
$env:TRAVEL_AI_API_KEY="your-api-key"
$env:TRAVEL_AI_ENDPOINT="https://open.bigmodel.cn/api/paas/v4/chat/completions"
$env:TRAVEL_AI_MODEL="glm-4-flash-250414"
```

Supported settings:

- `TRAVEL_AI_API_KEY` / `GLM_API_KEY` / `ZHIPUAI_API_KEY`
- `TRAVEL_AI_ENDPOINT` / `GLM_ENDPOINT`
- `TRAVEL_AI_MODEL` / `GLM_MODEL`
- `TRAVEL_AI_TIMEOUT` / `GLM_TIMEOUT`
- `TRAVEL_AI_DISABLE=1` to force local-only answers

## Tests

```powershell
python -m pytest
```

The test suite covers refresh caching, city search, preference weights, ML prediction, assistant endpoints, page routes, and the auto-refresh switch.

## Project Layout

```text
app.py          Flask application entry
config/         City, source, preference, weight, and refresh configuration
crawler/        Weather, air-quality, and historical-data crawlers
service/        Cleaning, SQLite, scoring, ranking, search, prediction, and assistant logic
web/            Flask routes, templates, and static assets
data/           Raw data, processed data, and SQLite database
scripts/        Manual refresh scripts
docs/           Requirements, notes, screenshots, and presentation assets
tests/          Automated tests
```

## Limitations

- Free upstream APIs may be rate-limited or temporarily unavailable.
- Pages read from SQLite by default and do not force a full fetch on every visit.
- Auto refresh is disabled by default and is intended to be enabled only when needed.
- ML prediction quality depends on historical sample coverage; confidence is lower when samples are insufficient.
