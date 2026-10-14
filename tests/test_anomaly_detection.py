"""Unit tests for rolling Median and MAD anomaly detection."""

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.anomaly_detection import detect_anomalies_for_sensor
from src.database import bulk_upsert_measurements, init_db, upsert_location, upsert_sensor
from src.models import Anomaly, Measurement


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_guardrail_requires_min_48_observations(db_session):
    upsert_location(db_session, {"id": 1, "name": "Station 1", "latitude": 17.3, "longitude": 78.4})
    upsert_sensor(db_session, {"id": 10, "location_id": 1, "parameter": "pm25", "unit": "µg/m³"})
    db_session.commit()

    base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    # Insert 40 observations (below 48 minimum requirement)
    records = []
    for i in range(40):
        records.append({
            "sensor_id": 10,
            "location_id": 1,
            "parameter": "pm25",
            "value": 30.0 if i < 39 else 999.0,  # last one is extreme spike
            "unit": "µg/m³",
            "value_original": 30.0 if i < 39 else 999.0,
            "unit_original": "µg/m³",
            "measured_at_utc": base_time + timedelta(hours=i),
            "ingested_at_utc": datetime.now(timezone.utc),
            "quality_flag": "valid",
            "source": "openaq_v3",
        })
    bulk_upsert_measurements(db_session, records)
    db_session.commit()

    # Must NOT flag because count < 48
    anomalies = detect_anomalies_for_sensor(db_session, sensor_id=10, min_observations=48)
    assert len(anomalies) == 0


def test_anomaly_flagged_with_48_observations(db_session):
    upsert_location(db_session, {"id": 1, "name": "Station 1", "latitude": 17.3, "longitude": 78.4})
    upsert_sensor(db_session, {"id": 10, "location_id": 1, "parameter": "pm25", "unit": "µg/m³"})
    db_session.commit()

    base_time = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
    # Insert 55 observations: first 50 stable around 35 µg/m³, then massive spike
    records = []
    for i in range(50):
        records.append({
            "sensor_id": 10,
            "location_id": 1,
            "parameter": "pm25",
            "value": 35.0 + (i % 3),
            "unit": "µg/m³",
            "value_original": 35.0 + (i % 3),
            "unit_original": "µg/m³",
            "measured_at_utc": base_time + timedelta(hours=i),
            "ingested_at_utc": datetime.now(timezone.utc),
            "quality_flag": "valid",
            "source": "openaq_v3",
        })

    # Add extreme anomaly at observation 51
    records.append({
        "sensor_id": 10,
        "location_id": 1,
        "parameter": "pm25",
        "value": 650.0,
        "unit": "µg/m³",
        "value_original": 650.0,
        "unit_original": "µg/m³",
        "measured_at_utc": base_time + timedelta(hours=50),
        "ingested_at_utc": datetime.now(timezone.utc),
        "quality_flag": "valid",
        "source": "openaq_v3",
    })

    bulk_upsert_measurements(db_session, records)
    db_session.commit()

    anomalies = detect_anomalies_for_sensor(db_session, sensor_id=10, min_observations=48)
    assert len(anomalies) >= 1
    anom = anomalies[0]
    assert anom.observed_value == 650.0
    assert anom.baseline_median >= 34.0
    assert anom.expected_high < 650.0
    assert anom.severity in ("medium", "high")
