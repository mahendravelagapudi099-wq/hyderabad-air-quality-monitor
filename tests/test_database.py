"""Unit tests for database models and idempotent upsert operations."""

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


@pytest.fixture
def in_memory_session():
    """Create an isolated in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_upsert_location_idempotent(in_memory_session):
    loc_data = {
        "id": 407,
        "name": "Zoo Park, Hyderabad",
        "latitude": 17.3497,
        "longitude": 78.4514,
        "country": "IN",
        "timezone": "Asia/Kolkata",
    }
    loc1, created1 = upsert_location(in_memory_session, loc_data)
    in_memory_session.commit()
    assert created1 is True
    assert loc1.name == "Zoo Park, Hyderabad"

    # Upsert again with updated name
    loc_data["name"] = "Zoo Park, Hyderabad - TSPCB"
    loc2, created2 = upsert_location(in_memory_session, loc_data)
    in_memory_session.commit()
    assert created2 is False
    assert loc2.id == 407
    assert loc2.name == "Zoo Park, Hyderabad - TSPCB"

    # Verify only 1 record exists
    count = in_memory_session.query(Location).count()
    assert count == 1


def test_upsert_measurements_idempotent(in_memory_session):
    # Setup parent location and sensor
    loc, _ = upsert_location(
        in_memory_session,
        {"id": 407, "name": "Zoo Park", "latitude": 17.3, "longitude": 78.4},
    )
    sensor, _ = upsert_sensor(
        in_memory_session,
        {"id": 1001, "location_id": 407, "parameter": "pm25", "unit": "µg/m³"},
    )
    in_memory_session.commit()

    dt = datetime(2026, 10, 14, 10, 0, 0, tzinfo=timezone.utc)
    records = [
        {
            "sensor_id": 1001,
            "location_id": 407,
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
    ]

    # First insert
    bulk_upsert_measurements(in_memory_session, records)
    in_memory_session.commit()
    assert in_memory_session.query(Measurement).count() == 1
    m1 = in_memory_session.query(Measurement).first()
    assert m1.value == 45.0

    # Second insert with updated value (idempotency check)
    records[0]["value"] = 52.0
    records[0]["value_original"] = 52.0
    bulk_upsert_measurements(in_memory_session, records)
    in_memory_session.commit()

    # Still exactly 1 record, value updated
    assert in_memory_session.query(Measurement).count() == 1
    m2 = in_memory_session.query(Measurement).first()
    assert m2.value == 52.0
