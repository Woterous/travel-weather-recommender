from __future__ import annotations

import sqlite3
from pathlib import Path
import re

import pandas as pd

from config.cities import CITIES


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "db" / "weather_recommender.sqlite3"


def _sanitize_refresh_message(message: str) -> str:
    cleaned = re.sub(
        r"历史数据抓取失败:\s*([^-\s]+)\s*->\s*429 Client Error:.*?(?=(?:\s+[^\s]+数据抓取失败:)|$)",
        r"历史数据暂时不可用：\1 请求过于频繁，本次未更新，请稍后重试。",
        message,
    )
    cleaned = re.sub(
        r"(未来天气补充数据失败|AQI 数据抓取失败|历史数据抓取失败|未来天气 API 数据失败|AQI 数据失败|历史数据失败):\s*([^-\s]+)\s*->\s*[^。]*",
        r"\1：\2 本次未更新，请稍后重试。",
        cleaned,
    )
    cleaned = re.sub(r"https?://\S+", "", cleaned).strip()
    return cleaned


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def ensure_database() -> None:
    connection = get_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS forecast_daily (
                city_slug TEXT NOT NULL,
                city_name TEXT NOT NULL,
                date TEXT NOT NULL,
                max_temp REAL,
                min_temp REAL,
                avg_temp REAL,
                weather_type TEXT,
                weather_detail TEXT,
                wind_direction TEXT,
                wind_speed_kmh REAL,
                wind_level INTEGER,
                precipitation_mm REAL,
                rain_flag INTEGER,
                aqi REAL,
                source_type TEXT,
                source_name TEXT,
                crawl_time TEXT,
                PRIMARY KEY (city_slug, date)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS history_monthly (
                city_slug TEXT NOT NULL,
                city_name TEXT NOT NULL,
                month_key TEXT NOT NULL,
                month_num INTEGER NOT NULL,
                avg_max_temp REAL,
                avg_min_temp REAL,
                avg_temp REAL,
                rainy_days INTEGER,
                rainy_ratio REAL,
                comfortable_days_ratio REAL,
                temp_std REAL,
                avg_wind_speed_kmh REAL,
                source_type TEXT,
                source_name TEXT,
                crawl_time TEXT,
                PRIMARY KEY (city_slug, month_key)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS history_daily (
                city_slug TEXT NOT NULL,
                city_name TEXT NOT NULL,
                date TEXT NOT NULL,
                max_temp REAL,
                min_temp REAL,
                avg_temp REAL,
                weather_detail TEXT,
                precipitation_mm REAL,
                rain_flag INTEGER,
                wind_speed_kmh REAL,
                month_num INTEGER,
                day_of_year INTEGER,
                source_type TEXT,
                source_name TEXT,
                crawl_time TEXT,
                PRIMARY KEY (city_slug, date)
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS refresh_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                refresh_time TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS added_cities (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                pinyin TEXT,
                latitude REAL,
                longitude REAL,
                province TEXT,
                country TEXT,
                added_time TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        seeded = cursor.execute(
            "SELECT value FROM app_state WHERE key = 'default_cities_seeded'"
        ).fetchone()
        if not seeded:
            cursor.executemany(
                """
                INSERT OR IGNORE INTO added_cities
                    (slug, name, pinyin, latitude, longitude, province, country, added_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                [(city.slug, city.name, city.pinyin, city.latitude, city.longitude, "城市库", "中国") for city in CITIES],
            )
            cursor.execute(
                "INSERT INTO app_state (key, value) VALUES ('default_cities_seeded', '1')"
            )
        connection.commit()
    finally:
        connection.close()


def write_dataframe(df: pd.DataFrame, table_name: str, replace: bool = True) -> None:
    ensure_database()
    connection = get_connection()
    try:
        if replace:
            connection.execute(f"DELETE FROM {table_name}")
        df.to_sql(table_name, connection, if_exists="append", index=False)
        connection.commit()
    finally:
        connection.close()


def write_city_dataframe(df: pd.DataFrame, table_name: str, city_slug: str) -> None:
    ensure_database()
    connection = get_connection()
    try:
        connection.execute(f"DELETE FROM {table_name} WHERE city_slug = ?", (city_slug,))
        if not df.empty:
            df.to_sql(table_name, connection, if_exists="append", index=False)
        connection.commit()
    finally:
        connection.close()


def delete_city_dataframe(table_name: str, city_slug: str) -> None:
    ensure_database()
    connection = get_connection()
    try:
        connection.execute(f"DELETE FROM {table_name} WHERE city_slug = ?", (city_slug,))
        connection.commit()
    finally:
        connection.close()


def log_refresh(refresh_time: str, status: str, message: str) -> None:
    ensure_database()
    connection = get_connection()
    try:
        connection.execute(
            "INSERT INTO refresh_log (refresh_time, status, message) VALUES (?, ?, ?)",
            (refresh_time, status, message),
        )
        connection.commit()
    finally:
        connection.close()


class WeatherRepository:
    def __init__(self) -> None:
        ensure_database()

    def _read_df(self, query: str, params: tuple = ()) -> pd.DataFrame:
        connection = get_connection()
        try:
            return pd.read_sql_query(query, connection, params=params)
        finally:
            connection.close()

    def get_forecast_dates(self) -> list[str]:
        df = self._read_df("SELECT DISTINCT date FROM forecast_daily ORDER BY date")
        return df["date"].tolist()

    def get_forecast_for_date(self, date_text: str) -> pd.DataFrame:
        return self._read_df(
            "SELECT * FROM forecast_daily WHERE date = ? ORDER BY city_slug",
            (date_text,),
        )

    def get_forecast_daily(self, city_slug: str | None = None) -> pd.DataFrame:
        if city_slug:
            return self.get_city_forecast(city_slug)
        return self._read_df("SELECT * FROM forecast_daily ORDER BY date, city_slug")

    def get_city_forecast(self, city_slug: str) -> pd.DataFrame:
        return self._read_df(
            "SELECT * FROM forecast_daily WHERE city_slug = ? ORDER BY date",
            (city_slug,),
        )

    def get_available_cities(self) -> list[dict]:
        df = self._read_df(
            """
            SELECT slug AS city_slug, name AS city_name, added_time AS crawl_time
            FROM added_cities
            ORDER BY city_name
            """
        )
        if df.empty:
            return []
        return df.rename(columns={"city_slug": "slug", "city_name": "name"}).to_dict("records")

    def add_city_record(self, city, province: str = "", country: str = "") -> None:
        connection = get_connection()
        try:
            connection.execute(
                """
                INSERT INTO added_cities
                    (slug, name, pinyin, latitude, longitude, province, country, added_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(slug) DO UPDATE SET
                    name = excluded.name,
                    pinyin = excluded.pinyin,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    province = excluded.province,
                    country = excluded.country,
                    added_time = excluded.added_time
                """,
                (
                    city.slug,
                    city.name,
                    city.pinyin,
                    city.latitude,
                    city.longitude,
                    province,
                    country,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def get_added_cities(self) -> list[dict]:
        df = self._read_df(
            """
            SELECT slug, name, pinyin, latitude, longitude, province, country, added_time
            FROM added_cities
            ORDER BY added_time DESC
            """
        )
        if df.empty:
            return []
        return df.to_dict("records")

    def get_city_record(self, city_slug: str) -> dict | None:
        df = self._read_df(
            """
            SELECT slug, name, pinyin, latitude, longitude, province, country
            FROM added_cities
            WHERE slug = ?
            """,
            (city_slug,),
        )
        if df.empty:
            return None
        return df.iloc[0].to_dict()

    def get_added_city_slugs(self) -> set[str]:
        df = self._read_df("SELECT slug FROM added_cities")
        if df.empty:
            return set()
        return {str(slug) for slug in df["slug"].dropna().tolist()}

    def prune_data_for_removed_cities(self) -> int:
        active_slugs = self.get_added_city_slugs()
        deleted = 0
        connection = get_connection()
        try:
            if not active_slugs:
                for table_name in ["forecast_daily", "history_monthly", "history_daily"]:
                    cursor = connection.execute(f"DELETE FROM {table_name}")
                    deleted += cursor.rowcount
                connection.commit()
                return deleted

            placeholders = ",".join("?" for _ in active_slugs)
            params = tuple(active_slugs)
            for table_name in ["forecast_daily", "history_monthly", "history_daily"]:
                cursor = connection.execute(
                    f"DELETE FROM {table_name} WHERE city_slug NOT IN ({placeholders})",
                    params,
                )
                deleted += cursor.rowcount
            connection.commit()
            return deleted
        finally:
            connection.close()

    def forecast_cache_is_current(self, city_slug: str, today: str) -> bool:
        df = self._read_df(
            """
            SELECT COUNT(*) AS row_count
            FROM forecast_daily
            WHERE city_slug = ?
              AND date >= ?
              AND crawl_time >= ?
            """,
            (city_slug, today, f"{today}T00:00:00"),
        )
        if df.empty:
            return False
        return int(df.iloc[0]["row_count"] or 0) >= 5

    def aqi_cache_is_current(self, city_slug: str, today: str) -> bool:
        df = self._read_df(
            """
            SELECT COUNT(*) AS row_count
            FROM forecast_daily
            WHERE city_slug = ?
              AND date >= ?
              AND crawl_time >= ?
              AND aqi IS NOT NULL
            """,
            (city_slug, today, f"{today}T00:00:00"),
        )
        if df.empty:
            return False
        return int(df.iloc[0]["row_count"] or 0) >= 5

    def delete_city_record(self, city_slug: str, purge_cached_data: bool = True) -> bool:
        connection = get_connection()
        try:
            cursor = connection.execute("DELETE FROM added_cities WHERE slug = ?", (city_slug,))
            deleted = cursor.rowcount > 0
            if deleted and purge_cached_data:
                for table_name in ["forecast_daily", "history_monthly", "history_daily"]:
                    connection.execute(f"DELETE FROM {table_name} WHERE city_slug = ?", (city_slug,))
            connection.commit()
            return deleted
        finally:
            connection.close()

    def delete_added_city(self, city_slug: str, purge_cached_data: bool = True) -> bool:
        return self.delete_city_record(city_slug, purge_cached_data=purge_cached_data)

    def get_city_meta(self, city_slug: str) -> dict | None:
        df = self._read_df(
            """
            SELECT city_slug, city_name
            FROM forecast_daily
            WHERE city_slug = ?
            ORDER BY crawl_time DESC
            LIMIT 1
            """,
            (city_slug,),
        )
        if df.empty:
            return None
        row = df.iloc[0]
        return {"slug": row["city_slug"], "name": row["city_name"], "pinyin": row["city_slug"]}

    def get_history_monthly(self, city_slug: str | None = None) -> pd.DataFrame:
        if city_slug:
            return self._read_df(
                "SELECT * FROM history_monthly WHERE city_slug = ? ORDER BY month_key",
                (city_slug,),
            )
        return self._read_df("SELECT * FROM history_monthly ORDER BY city_slug, month_key")

    def get_history_daily(self, city_slug: str | None = None) -> pd.DataFrame:
        if city_slug:
            return self._read_df(
                "SELECT * FROM history_daily WHERE city_slug = ? ORDER BY date",
                (city_slug,),
            )
        return self._read_df("SELECT * FROM history_daily ORDER BY city_slug, date")

    def get_history_daily_coverage(self, city_slug: str) -> dict:
        df = self._read_df(
            """
            SELECT COUNT(*) AS row_count, MIN(date) AS start_date, MAX(date) AS end_date
            FROM history_daily
            WHERE city_slug = ?
            """,
            (city_slug,),
        )
        if df.empty:
            return {"row_count": 0, "start_date": None, "end_date": None}
        row = df.iloc[0].to_dict()
        return {
            "row_count": int(row.get("row_count") or 0),
            "start_date": row.get("start_date"),
            "end_date": row.get("end_date"),
        }

    def get_data_version(self) -> str:
        df = self._read_df(
            """
            SELECT
                COALESCE((SELECT MAX(crawl_time) FROM forecast_daily), '') AS forecast_version,
                COALESCE((SELECT MAX(crawl_time) FROM history_daily), '') AS history_version,
                COALESCE((SELECT MAX(crawl_time) FROM history_monthly), '') AS history_monthly_version,
                COALESCE((SELECT MAX(added_time) FROM added_cities), '') AS added_city_version,
                COALESCE((SELECT COUNT(*) FROM forecast_daily), 0) AS forecast_rows,
                COALESCE((SELECT COUNT(*) FROM history_daily), 0) AS history_rows,
                COALESCE((SELECT COUNT(*) FROM history_monthly), 0) AS history_monthly_rows,
                COALESCE((SELECT COUNT(*) FROM added_cities), 0) AS added_city_rows
            """
        )
        if df.empty:
            return "empty"
        row = df.iloc[0]
        return (
            f"{row['forecast_version']}|{row['history_version']}|{row['history_monthly_version']}|"
            f"{row['added_city_version']}|{row['forecast_rows']}|{row['history_rows']}|"
            f"{row['history_monthly_rows']}|{row['added_city_rows']}"
        )

    def get_latest_refresh_info(self) -> dict:
        df = self._read_df(
            "SELECT refresh_time, status, message FROM refresh_log ORDER BY id DESC LIMIT 1"
        )
        if df.empty:
            return {"refresh_time": "未刷新", "status": "empty", "message": "当前数据库中还没有抓取记录。"}
        row = df.iloc[0].to_dict()
        row["message"] = _sanitize_refresh_message(str(row.get("message", "")))
        return row

    def aqi_available(self) -> bool:
        df = self._read_df("SELECT MAX(aqi) AS max_aqi FROM forecast_daily")
        return not df.empty and pd.notna(df.iloc[0]["max_aqi"])
