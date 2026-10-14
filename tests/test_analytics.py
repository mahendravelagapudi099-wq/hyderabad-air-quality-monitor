"""Unit tests for analytics and dashboard aggregation queries."""

from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import (
    get_anomalies_df,
    get_available_parameters,
    get_ingestion_history_df,
    get_locations_list,
    get_measurement_timeseries,
    get_overview_metrics,
)
from src.database import bulk_upsert_measurements, init_db, upsert_location, upsert_sensor


@pytest.fixture
def empty_session():
    engine = create_engine("sqlite:///:memory:")
    init_db(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_overview_metrics_on_empty_db(empty_session):
    metrics = get_overview_metrics(empty_session)
    assert metrics["station_count"] == 0
    assert metrics["sensor_count"] == 0
    assert metrics["total_records"] == 0
    assert metrics["total_anomalies"] == 0
    assert metrics["freshness_status"] == "No Data"


def test_queries_on_empty_db_do_not_crash(empty_session):
    assert get_locations_list(empty_session) == []
    assert get_available_parameters(empty_session) == []
    assert get_measurement_timeseries(empty_session).empty is True
    assert get_anomalies_df(empty_session).empty is True
    assert get_ingestion_history_df(empty_session).empty is True


def test_populated_analytics(empty_session):
    upsert_location(empty_session, {"id": 1, "name": "Station A", "latitude": 17.3, "longitude": 78.4})
    upsert_sensor(empty_session, {"id": 101, "location_id": 1, "parameter": "pm25", "unit": "µg/m³"})
    empty_session.commit()

    records = [
        {
            "sensor_id": 101,
            "location_id": 1,
            "parameter": "pm25",
            "value": 40.0,
            "unit": "µg/m³",
            "value_original": 40.0,
            "unit_original": "µg/m³",
            "measured_at_utc": datetime.now(timezone.utc),
            "ingested_at_utc": datetime.now(timezone.utc),
            "quality_flag": "valid",
            "source": "openaq_v3",
        }
    ]
    bulk_upsert_measurements(empty_session, records)
    empty_session.commit()

    metrics = get_overview_metrics(empty_session)
    assert metrics["station_count"] == 1
    assert metrics["total_records"] == 1
    assert "Live" in metrics["freshness_status"] or "Recent" in metrics["freshness_status"]

    df = get_measurement_timeseries(empty_session, parameters=["pm25"])
    assert len(df) == 1
    assert "measured_at_ist" in df.columns
    assert df.iloc[0]["value"] == 40.0


def test_pipeline_health_stats(empty_session):
    from src.analytics import get_pipeline_health_stats
    from src.models import IngestionRun

    empty_session.add(
        IngestionRun(
            started_at=datetime.now(timezone.utc),
            status="completed",
            rows_received=100,
            rows_inserted=95,
            rows_rejected=5,
        )
    )
    empty_session.commit()

    stats = get_pipeline_health_stats(empty_session)
    assert stats["total_runs"] == 1
    assert stats["completed_runs"] == 1
    assert stats["success_rate"] == 100.0
    assert stats["total_inserted"] == 95
    assert stats["total_rejected"] == 5


def test_filtered_measurements_and_insights(empty_session):
    from src.analytics import get_automated_insights, get_filtered_measurements_df

    upsert_location(empty_session, {"id": 1, "name": "Station A", "latitude": 17.3, "longitude": 78.4})
    upsert_sensor(empty_session, {"id": 101, "location_id": 1, "parameter": "pm25", "unit": "µg/m³"})
    empty_session.commit()

    bulk_upsert_measurements(
        empty_session,
        [
            {
                "sensor_id": 101,
                "location_id": 1,
                "parameter": "pm25",
                "value": 45.0,
                "unit": "µg/m³",
                "value_original": 45.0,
                "unit_original": "µg/m³",
                "measured_at_utc": datetime.now(timezone.utc),
                "ingested_at_utc": datetime.now(timezone.utc),
                "quality_flag": "valid",
                "source": "openaq_v3",
            }
        ],
    )
    empty_session.commit()

    # Data explorer query
    df_exp = get_filtered_measurements_df(empty_session, parameters=["pm25"])
    assert len(df_exp) == 1
    assert df_exp.iloc[0]["station_name"] == "Station A"
    assert df_exp.iloc[0]["value"] == 45.0

    # Automated insights
    insights = get_automated_insights(empty_session, days=7)
    assert "insights" in insights
    assert len(insights["insights"]) >= 2
    assert any("PM2.5" in s for s in insights["insights"])
