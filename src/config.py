"""Configuration settings for Hyderabad Air Quality Monitor."""

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Load environment variables
load_dotenv(PROJECT_ROOT / ".env")


def get_database_url() -> str:
    """Retrieve DATABASE_URL from env or Streamlit secrets, normalizing postgres:// to postgresql://."""
    url = os.getenv("DATABASE_URL")
    if not url:
        try:
            import streamlit as st
            if hasattr(st, "secrets") and "DATABASE_URL" in st.secrets:
                url = st.secrets["DATABASE_URL"]
        except Exception:
            pass
    if not url:
        url = f"sqlite:///{DATA_DIR / 'airquality.db'}"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def get_openaq_api_key() -> str:
    """Retrieve OPENAQ_API_KEY from env or Streamlit secrets."""
    key = os.getenv("OPENAQ_API_KEY")
    if not key:
        try:
            import streamlit as st
            if hasattr(st, "secrets") and "OPENAQ_API_KEY" in st.secrets:
                key = st.secrets["OPENAQ_API_KEY"]
        except Exception:
            pass
    return key or ""


@dataclass(frozen=True)
class Settings:
    """Application configuration settings."""

    # API Configuration
    OPENAQ_API_KEY: str = get_openaq_api_key()
    OPENAQ_BASE_URL: str = os.getenv("OPENAQ_BASE_URL", "https://api.openaq.org/v3")
    API_TIMEOUT_SECONDS: int = int(os.getenv("API_TIMEOUT_SECONDS", "20"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "4"))
    BACKOFF_FACTOR: float = float(os.getenv("BACKOFF_FACTOR", "2.0"))

    # Database Configuration (PostgreSQL-ready, default SQLite)
    DATABASE_URL: str = get_database_url()

    # Geographic Bounds for Hyderabad and outskirts
    # Bounding Box format: min_lon, min_lat, max_lon, max_lat
    HYDERABAD_BBOX: str = os.getenv("HYDERABAD_BBOX", "78.10,17.10,78.80,17.70")
    HYDERABAD_LAT: float = 17.3850
    HYDERABAD_LON: float = 78.4867
    HYDERABAD_RADIUS_METERS: int = 25000

    # Pollutants prioritized
    PRIORITY_PARAMETERS: tuple = ("pm25", "pm10", "no2", "so2", "co", "o3")

    # Timezones
    STORAGE_TIMEZONE: str = "UTC"
    DISPLAY_TIMEZONE: str = "Asia/Kolkata"

    # Ingestion & Quality Parameters
    BACKFILL_DAYS: int = 30
    DAILY_REFETCH_DAYS: int = 3
    MIN_OBSERVATIONS_FOR_ANOMALY: int = 48
    MAD_THRESHOLD: float = 3.5

    def validate(self) -> None:
        """Validate required configuration."""
        if not self.OPENAQ_API_KEY:
            raise ValueError(
                "OPENAQ_API_KEY is not configured. Please set OPENAQ_API_KEY in your environment or .env file."
            )


settings = Settings()
