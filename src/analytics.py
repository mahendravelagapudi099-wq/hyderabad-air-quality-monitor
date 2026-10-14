"""Analytics and aggregation queries for the Streamlit dashboard."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models import Anomaly, IngestionRun, Location, Measurement, Sensor


def get_overview_metrics(session: Session) -> Dict[str, Any]:
    """Retrieve high-level overview metrics for the dashboard."""
    station_count = session.query(func.count(Location.id)).scalar() or 0
    sensor_count = session.query(func.count(Sensor.id)).scalar() or 0
    total_records = session.query(func.count(Measurement.id)).scalar() or 0
    total_anomalies = session.query(func.count(Anomaly.id)).scalar() or 0

    latest_measurement = (
        session.query(Measurement.measured_at_utc)
        .order_by(Measurement.measured_at_utc.desc())
        .first()
    )
    latest_ts = latest_measurement[0] if latest_measurement else None

    last_run = (
        session.query(IngestionRun)
        .order_by(IngestionRun.started_at.desc())
        .first()
    )

    freshness_status = "No Data"
    if latest_ts:
        now_utc = datetime.now(timezone.utc)
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)
        diff_hours = (now_utc - latest_ts).total_seconds() / 3600.0
        if diff_hours <= 6:
            freshness_status = f"Live ({diff_hours:.1f}h ago)"
        elif diff_hours <= 24:
            freshness_status = f"Recent ({diff_hours:.1f}h ago)"
        else:
            freshness_status = f"Stale ({diff_hours/24:.1f}d ago)"

    return {
        "station_count": station_count,
        "sensor_count": sensor_count,
        "total_records": total_records,
        "total_anomalies": total_anomalies,
        "latest_measurement_utc": latest_ts,
        "freshness_status": freshness_status,
        "last_run_status": last_run.status if last_run else "Never Run",
        "last_run_finished": last_run.finished_at if last_run else None,
        "last_run_inserted": last_run.rows_inserted if last_run else 0,
    }


def get_locations_list(session: Session) -> List[Dict[str, Any]]:
    """Return all monitoring stations with coordinates."""
    locations = session.query(Location).order_by(Location.name.asc()).all()
    return [
        {
            "id": loc.id,
            "name": loc.name,
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "timezone": loc.timezone,
        }
        for loc in locations
    ]


def get_available_parameters(session: Session) -> List[str]:
    """Get list of distinct parameters present in measurements."""
    params = (
        session.query(Measurement.parameter)
        .distinct()
        .order_by(Measurement.parameter.asc())
        .all()
    )
    return [p[0] for p in params]


def get_measurement_timeseries(
    session: Session,
    parameters: Optional[List[str]] = None,
    location_ids: Optional[List[int]] = None,
    days: int = 7,
) -> pd.DataFrame:
    """Fetch time series measurements dataframe for visualization."""
    query = session.query(
        Measurement.measured_at_utc,
        Measurement.parameter,
        Measurement.value,
        Measurement.unit,
        Location.name.label("location_name"),
        Location.id.label("location_id"),
    ).join(Location, Measurement.location_id == Location.id)

    if days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        query = query.filter(Measurement.measured_at_utc >= cutoff)

    if parameters:
        query = query.filter(Measurement.parameter.in_(parameters))

    if location_ids:
        query = query.filter(Measurement.location_id.in_(location_ids))

    query = query.order_by(Measurement.measured_at_utc.asc())

    results = query.all()
    if not results:
        return pd.DataFrame(
            columns=["measured_at_utc", "measured_at_ist", "parameter", "value", "unit", "location_name", "location_id"]
        )

    df = pd.DataFrame(results)
    # Convert UTC to IST for display (handling both tz-aware and tz-naive from SQLite)
    ts = pd.to_datetime(df["measured_at_utc"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("UTC")
    df["measured_at_ist"] = ts.dt.tz_convert("Asia/Kolkata")
    return df


def get_anomalies_df(session: Session, limit: int = 100) -> pd.DataFrame:
    """Fetch recent anomalies with location metadata."""
    query = (
        session.query(
            Anomaly.id,
            Anomaly.measured_at_utc,
            Anomaly.parameter,
            Anomaly.observed_value,
            Anomaly.baseline_median,
            Anomaly.expected_low,
            Anomaly.expected_high,
            Anomaly.severity,
            Anomaly.method,
            Location.name.label("location_name"),
        )
        .outerjoin(Location, Anomaly.location_id == Location.id)
        .order_by(Anomaly.measured_at_utc.desc())
        .limit(limit)
    )

    results = query.all()
    if not results:
        return pd.DataFrame(
            columns=[
                "id", "measured_at_utc", "measured_at_ist", "location_name",
                "parameter", "observed_value", "baseline_median", "expected_low",
                "expected_high", "severity", "method"
            ]
        )

    df = pd.DataFrame(results)
    ts = pd.to_datetime(df["measured_at_utc"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("UTC")
    df["measured_at_ist"] = ts.dt.tz_convert("Asia/Kolkata")
    return df


def get_ingestion_history_df(session: Session, limit: int = 30) -> pd.DataFrame:
    """Fetch ingestion audit run history."""
    runs = (
        session.query(IngestionRun)
        .order_by(IngestionRun.started_at.desc())
        .limit(limit)
        .all()
    )
    if not runs:
        return pd.DataFrame()

    data = [
        {
            "Run ID": r.id,
            "Started (IST)": pd.to_datetime(r.started_at).tz_convert("Asia/Kolkata").strftime("%Y-%m-%d %H:%M:%S") if r.started_at else None,
            "Status": r.status,
            "Requests": r.requests_made,
            "Received": r.rows_received,
            "Inserted": r.rows_inserted,
            "Updated": r.rows_updated,
            "Rejected": r.rows_rejected,
            "Error": r.error_message,
        }
        for r in runs
    ]
    return pd.DataFrame(data)
