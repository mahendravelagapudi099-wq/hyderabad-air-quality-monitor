"""Tests for PostgreSQL compatibility, upserts, constraints, and timestamps.

Runs only when TEST_POSTGRES_URL or POSTGRES_DATABASE_URL is configured.
"""

import os
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database import (
    bulk_upsert_measurements,
    init_db,
    upsert_location,
    upsert_sensor,
)
from src.models import Base, Location, Measurement, Sensor

POSTGRES_URL = os.getenv("TEST_POSTGRES_URL") or os.getenv("POSTGRES_DATABASE_URL") or os.getenv("DATABASE_URL")
if POSTGRES_URL and POSTGRES_URL.startswith("postgres://"):
    POSTGRES_URL = POSTGRES_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif POSTGRES_URL and POSTGRES_URL.startswith("postgresql://") and not POSTGRES_URL.startswith("postgresql+"):
    POSTGRES_URL = POSTGRES_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
# Skip if the URL is SQLite (e.g. default fallback)
if POSTGRES_URL and POSTGRES_URL.startswith("sqlite"):
    POSTGRES_URL = None


@pytest.mark.skipif(
    not POSTGRES_URL,
    reason="PostgreSQL test URL not configured. Set TEST_POSTGRES_URL or POSTGRES_DATABASE_URL to run.",
)
class TestPostgresIntegration:
    """PostgreSQL integration suite."""

    @pytest.fixture(scope="class")
    def pg_engine(self):
        engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
        Base.metadata.create_all(bind=engine)
        yield engine

    @pytest.fixture
    def pg_session(self, pg_engine):
        Session = sessionmaker(bind=pg_engine)
        session = Session()
        yield session
        session.rollback()
        session.close()

    def test_postgres_location_sensor_upsert(self, pg_session):
        loc, created = upsert_location(
            pg_session,
            {
                "id": 99999,
                "name": "Test PG Location",
                "latitude": 17.38,
                "longitude": 78.48,
                "country": "IN",
                "timezone": "Asia/Kolkata",
            },
        )
        pg_session.flush()

        sensor, s_created = upsert_sensor(
            pg_session,
            {
                "id": 88888,
                "location_id": 99999,
                "parameter": "pm25",
                "unit": "µg/m³",
            },
        )
        pg_session.commit()
        assert sensor.parameter == "pm25"

    def test_postgres_measurement_upsert_idempotency(self, pg_session):
        dt = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
        record = {
            "sensor_id": 88888,
            "location_id": 99999,
            "parameter": "pm25",
            "value": 45.0,
            "unit": "µg/m³",
            "value_original": 45.0,
            "unit_original": "µg/m³",
            "measured_at_utc": dt,
            "ingested_at_utc": datetime.now(timezone.utc),
            "quality_flag": "valid",
            "source": "openaq_v3",
        }

        # First insert
        bulk_upsert_measurements(pg_session, [record])
        pg_session.commit()

        # Update value on same (sensor_id, parameter, measured_at_utc)
        record["value"] = 55.0
        bulk_upsert_measurements(pg_session, [record])
        pg_session.commit()

        m = (
            pg_session.query(Measurement)
            .filter(
                Measurement.sensor_id == 88888,
                Measurement.measured_at_utc == dt,
            )
            .first()
        )
        assert m is not None
        assert m.value == 55.0
