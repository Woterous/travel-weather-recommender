from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "db" / "weather_recommender.sqlite3"


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

    def get_city_forecast(self, city_slug: str) -> pd.DataFrame:
        return self._read_df(
            "SELECT * FROM forecast_daily WHERE city_slug = ? ORDER BY date",
            (city_slug,),
        )

    def get_available_cities(self) -> list[dict]:
        df = self._read_df(
            """
            SELECT city_slug, city_name, MAX(crawl_time) AS crawl_time
            FROM forecast_daily
            GROUP BY city_slug, city_name
            ORDER BY city_name
            """
        )
        if df.empty:
            return []
        return df.rename(columns={"city_slug": "slug", "city_name": "name"}).to_dict("records")

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

    def get_latest_refresh_info(self) -> dict:
        df = self._read_df(
            "SELECT refresh_time, status, message FROM refresh_log ORDER BY id DESC LIMIT 1"
        )
        if df.empty:
            return {"refresh_time": "未刷新", "status": "empty", "message": "当前数据库中还没有抓取记录。"}
        return df.iloc[0].to_dict()

    def aqi_available(self) -> bool:
        df = self._read_df("SELECT MAX(aqi) AS max_aqi FROM forecast_daily")
        return not df.empty and pd.notna(df.iloc[0]["max_aqi"])
