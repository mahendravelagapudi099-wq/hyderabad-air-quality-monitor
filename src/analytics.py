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
            "Quality Report": r.quality_report,
            "Error": r.error_message,
        }
        for r in runs
    ]
    return pd.DataFrame(data)


def get_pipeline_health_stats(session: Session) -> Dict[str, Any]:
    """Calculate overall pipeline run statistics and success rate."""
    total_runs = session.query(func.count(IngestionRun.id)).scalar() or 0
    completed_runs = (
        session.query(func.count(IngestionRun.id))
        .filter(IngestionRun.status == "completed")
        .scalar()
        or 0
    )
    failed_runs = (
        session.query(func.count(IngestionRun.id))
        .filter(IngestionRun.status == "failed")
        .scalar()
        or 0
    )
    success_rate = (completed_runs / total_runs * 100.0) if total_runs > 0 else 100.0

    total_inserted = (
        session.query(func.sum(IngestionRun.rows_inserted)).scalar() or 0
    )
    total_rejected = (
        session.query(func.sum(IngestionRun.rows_rejected)).scalar() or 0
    )

    return {
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "failed_runs": failed_runs,
        "success_rate": round(success_rate, 1),
        "total_inserted": total_inserted,
        "total_rejected": total_rejected,
    }


def get_filtered_measurements_df(
    session: Session,
    parameters: Optional[List[str]] = None,
    location_ids: Optional[List[int]] = None,
    quality_flags: Optional[List[str]] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 5000,
) -> pd.DataFrame:
    """Fetch tabular measurement records with filters for the Data Explorer and CSV export."""
    query = (
        session.query(
            Measurement.id,
            Location.name.label("station_name"),
            Measurement.parameter,
            Measurement.value,
            Measurement.unit,
            Measurement.value_original,
            Measurement.unit_original,
            Measurement.measured_at_utc,
            Measurement.quality_flag,
            Measurement.source,
        )
        .join(Location, Measurement.location_id == Location.id)
    )

    if parameters:
        query = query.filter(Measurement.parameter.in_(parameters))
    if location_ids:
        query = query.filter(Measurement.location_id.in_(location_ids))
    if quality_flags:
        query = query.filter(Measurement.quality_flag.in_(quality_flags))
    if date_from:
        query = query.filter(Measurement.measured_at_utc >= date_from)
    if date_to:
        query = query.filter(Measurement.measured_at_utc <= date_to)

    query = query.order_by(Measurement.measured_at_utc.desc()).limit(limit)
    results = query.all()

    if not results:
        return pd.DataFrame(
            columns=[
                "id", "station_name", "parameter", "value", "unit",
                "value_original", "unit_original", "measured_at_utc",
                "measured_at_ist", "quality_flag", "source"
            ]
        )

    df = pd.DataFrame(results)
    ts = pd.to_datetime(df["measured_at_utc"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("UTC")
    df["measured_at_ist"] = ts.dt.tz_convert("Asia/Kolkata")
    return df


def get_automated_insights(
    session: Session,
    days: int = 7,
    location_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Generate deterministic automated analytical insights based strictly on real query results.

    When data is insufficient for comparison, explicitly reports it instead of guessing.
    """
    now_utc = datetime.now(timezone.utc)
    curr_cutoff = now_utc - timedelta(days=days)
    prev_cutoff = curr_cutoff - timedelta(days=days)

    # Current period readings
    curr_q = session.query(
        Measurement.parameter,
        func.avg(Measurement.value).label("mean_val"),
        func.count(Measurement.id).label("count_val"),
    ).filter(Measurement.measured_at_utc >= curr_cutoff)

    # Previous period readings
    prev_q = session.query(
        Measurement.parameter,
        func.avg(Measurement.value).label("mean_val"),
        func.count(Measurement.id).label("count_val"),
    ).filter(
        Measurement.measured_at_utc >= prev_cutoff,
        Measurement.measured_at_utc < curr_cutoff,
    )

    if location_ids:
        curr_q = curr_q.filter(Measurement.location_id.in_(location_ids))
        prev_q = prev_q.filter(Measurement.location_id.in_(location_ids))

    curr_stats = {r[0]: (float(r[1]), int(r[2])) for r in curr_q.group_by(Measurement.parameter).all()}
    prev_stats = {r[0]: (float(r[1]), int(r[2])) for r in prev_q.group_by(Measurement.parameter).all()}

    # Station coverage
    total_stations = session.query(func.count(Location.id)).scalar() or 0
    active_in_curr_q = session.query(func.count(func.distinct(Measurement.location_id))).filter(
        Measurement.measured_at_utc >= curr_cutoff
    )
    if location_ids:
        active_in_curr_q = active_in_curr_q.filter(Measurement.location_id.in_(location_ids))
    active_stations_curr = active_in_curr_q.scalar() or 0

    station_coverage_pct = (
        round(active_stations_curr / total_stations * 100.0, 1)
        if total_stations > 0
        else 0.0
    )

    # Anomalies in period
    anom_q = session.query(func.count(Anomaly.id), func.max(Anomaly.observed_value)).filter(
        Anomaly.measured_at_utc >= curr_cutoff
    )
    if location_ids:
        anom_q = anom_q.filter(Anomaly.location_id.in_(location_ids))
    anom_res = anom_q.first()
    anom_count = anom_res[0] if anom_res else 0
    anom_max_spike = anom_res[1] if anom_res and anom_res[1] is not None else None

    # Construct narrative points strictly from real data
    insights: List[str] = []

    # 1. Particulate matter comparison
    for param, label in [("pm25", "PM2.5"), ("pm10", "PM10")]:
        if param in curr_stats:
            curr_mean, curr_n = curr_stats[param]
            if param in prev_stats and prev_stats[param][1] >= 24:
                prev_mean, prev_n = prev_stats[param]
                pct_change = ((curr_mean - prev_mean) / prev_mean) * 100.0
                direction = "increased by" if pct_change > 0 else "decreased by"
                insights.append(
                    f"**{label} Concentration**: Averaged **{curr_mean:.1f} µg/m³** over the selected window ({direction} {abs(pct_change):.1f}% compared to {prev_mean:.1f} µg/m³ in the preceding period)."
                )
            else:
                insights.append(
                    f"**{label} Concentration**: Averaged **{curr_mean:.1f} µg/m³** ({curr_n:,} observations). Insufficient historical observations in the preceding window ({prev_stats.get(param, (0, 0))[1]} records) for a comparative trend."
                )

    # 2. Coverage insight
    insights.append(
        f"**Station Coverage**: **{active_stations_curr} of {total_stations} stations ({station_coverage_pct}%)** recorded active telemetry during this timeframe."
    )

    # 3. Anomaly insight
    if anom_count > 0:
        spike_info = f" with a peak observed spike of {anom_max_spike:.1f}" if anom_max_spike else ""
        insights.append(
            f"**Statistical Outliers**: Flagged **{anom_count} anomalous sensor reading(s)** exceeding the 3.5× MAD threshold{spike_info}."
        )
    else:
        insights.append(
            "**Statistical Outliers**: Zero anomalies detected in this observation window; sensor concentrations remained within normal statistical dispersion."
        )

    return {
        "days": days,
        "insights": insights,
        "active_stations": active_stations_curr,
        "total_stations": total_stations,
        "coverage_pct": station_coverage_pct,
        "anomalies_count": anom_count,
    }
