import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.api_client import OpenAQClient
from src.config import settings
from src.database import (
    bulk_upsert_measurements,
    get_session,
    init_db,
    upsert_location,
    upsert_sensor,
)
from src.models import IngestionRun, Location, Measurement, Sensor
from src.transformation import transform_raw_measurement
from src.validation import validate_measurement
from src.anomaly_detection import run_anomaly_detection_pipeline

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Orchestrates OpenAQ data ingestion into SQLite/PostgreSQL."""

    def __init__(self, client: Optional[OpenAQClient] = None):
        self.client = client or OpenAQClient()

    def run(
        self,
        days_back: int = 3,
        session: Optional[Session] = None,
        max_locations: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Execute the ingestion pipeline.

        Args:
            days_back: Number of past days to query (e.g. 3 for daily rolling, 30 for backfill).
            session: Optional existing SQLAlchemy session.
            max_locations: Optional limit on locations to process.

        Returns:
            Dict containing execution summary metrics.
        """
        init_db()

        if session:
            return self._execute_run(days_back, session, max_locations)
        else:
            with get_session() as new_session:
                return self._execute_run(days_back, new_session, max_locations)

    def _execute_run(
        self,
        days_back: int,
        session: Session,
        max_locations: Optional[int] = None,
    ) -> Dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        start_date_str = (started_at - timedelta(days=days_back)).strftime("%Y-%m-%dT00:00:00Z")

        # Create audit record
        audit_run = IngestionRun(
            started_at=started_at,
            status="in_progress",
            requests_made=0,
            rows_received=0,
            rows_inserted=0,
            rows_updated=0,
            rows_rejected=0,
        )
        session.add(audit_run)
        session.flush()

        logger.info("Starting ingestion run %d (syncing past %d days from %s)...", audit_run.id, days_back, start_date_str)

        total_received = 0
        total_inserted = 0
        total_updated = 0
        total_rejected = 0
        rejection_reasons: Dict[str, int] = {}
        processed_stations = 0

        try:
            # 1. Fetch locations around Hyderabad
            locations = self.client.get_all_locations(bbox=settings.HYDERABAD_BBOX)
            logger.info("Discovered %d locations in Hyderabad bounding box.", len(locations))

            if max_locations:
                locations = locations[:max_locations]

            for loc in locations:
                loc_id = loc.get("id")
                coords = loc.get("coordinates") or {}
                lat = coords.get("latitude")
                lon = coords.get("longitude")
                if lat is None or lon is None:
                    continue

                # Upsert location
                upsert_location(
                    session,
                    {
                        "id": loc_id,
                        "name": loc.get("name", f"Station {loc_id}"),
                        "latitude": lat,
                        "longitude": lon,
                        "country": loc.get("country", {}).get("code", "IN") if isinstance(loc.get("country"), dict) else "IN",
                        "timezone": loc.get("timezone", settings.DISPLAY_TIMEZONE),
                        "owner_name": (loc.get("owner") or {}).get("name") if isinstance(loc.get("owner"), dict) else None,
                        "source_metadata": str(loc.get("provider", "")),
                    },
                )
                session.flush()
                processed_stations += 1

                # 2. Fetch and upsert sensors for location
                sensors = loc.get("sensors", [])
                if not sensors:
                    sensors = self.client.get_location_sensors(loc_id)

                for s in sensors:
                    s_id = s.get("id")
                    param_obj = s.get("parameter") or {}
                    param_name = (param_obj.get("name") if isinstance(param_obj, dict) else s.get("name", "")).lower().replace(".", "")
                    param_unit = param_obj.get("units") if isinstance(param_obj, dict) else ""
                    display_name = param_obj.get("displayName") if isinstance(param_obj, dict) else None

                    # Prioritize pollutants and weather metrics
                    upsert_sensor(
                        session,
                        {
                            "id": s_id,
                            "location_id": loc_id,
                            "parameter": param_name,
                            "unit": param_unit or "unknown",
                            "display_name": display_name,
                        },
                    )
                    session.flush()

                    # 3. Fetch measurements for this sensor (pagination over requested time window)
                    page = 1
                    limit = 100
                    sensor_raw_records = []

                    while True:
                        try:
                            # Use hourly aggregated endpoint for fast, clean, regular hourly records
                            data = self.client.get_sensor_hours(
                                sensor_id=s_id,
                                datetime_from=start_date_str,
                                limit=limit,
                                page=page,
                            )
                        except Exception as e:
                            logger.warning("Failed to fetch measurements for sensor %d (page %d): %s", s_id, page, e)
                            break

                        results = data.get("results", [])
                        if not results:
                            break

                        sensor_raw_records.extend(results)
                        meta = data.get("meta", {})
                        found = meta.get("found", 0)
                        if len(sensor_raw_records) >= found or len(results) < limit:
                            break
                        page += 1

                    # 4. Validate and transform records
                    valid_records: List[Dict[str, Any]] = []
                    for r in sensor_raw_records:
                        total_received += 1
                        is_valid, reason = validate_measurement(r)
                        if not is_valid:
                            total_rejected += 1
                            r_reason = reason or "unknown"
                            rejection_reasons[r_reason] = rejection_reasons.get(r_reason, 0) + 1
                            continue

                        transformed = transform_raw_measurement(
                            raw=r,
                            sensor_id=s_id,
                            location_id=loc_id,
                            param_fallback=param_name,
                            unit_fallback=param_unit,
                        )
                        valid_records.append(transformed)

                    # 5. Bulk upsert into database
                    if valid_records:
                        ins, upd = bulk_upsert_measurements(session, valid_records)
                        total_inserted += ins
                        total_updated += upd

                session.flush()

            # 6. Run Anomaly Detection Pipeline
            logger.info("Executing rolling anomaly detection...")
            new_anomalies_count = run_anomaly_detection_pipeline(session)
            logger.info("Anomaly detection completed (%d flagged).", new_anomalies_count)

            # 7. Perform Data Quality Audits
            quality_report = self._perform_quality_audits(session, total_received)

            # 8. Finalize Audit Run
            finished_at = datetime.now(timezone.utc)
            audit_run.finished_at = finished_at
            audit_run.status = "completed"
            audit_run.requests_made = self.client.requests_made
            audit_run.rows_received = total_received
            audit_run.rows_inserted = total_inserted
            audit_run.rows_updated = total_updated
            audit_run.rows_rejected = total_rejected
            audit_run.quality_report = json.dumps(quality_report)

            summary = {
                "run_id": audit_run.id,
                "status": "completed",
                "stations_processed": processed_stations,
                "requests_made": self.client.requests_made,
                "rows_received": total_received,
                "rows_inserted": total_inserted,
                "rows_updated": total_updated,
                "rows_rejected": total_rejected,
                "rejection_reasons": rejection_reasons,
                "anomalies_flagged": new_anomalies_count,
                "quality_report": quality_report,
                "duration_seconds": round((finished_at - started_at).total_seconds(), 2),
            }
            logger.info("Ingestion completed successfully: %s", summary)
            return summary

        except Exception as e:
            finished_at = datetime.now(timezone.utc)
            audit_run.finished_at = finished_at
            audit_run.status = "failed"
            audit_run.error_message = str(e)
            audit_run.requests_made = self.client.requests_made
            session.flush()
            logger.error("Ingestion run failed: %s", e, exc_info=True)
            raise

    def _perform_quality_audits(
        self,
        session: Session,
        current_rows: int,
    ) -> Dict[str, Any]:
        """Audit for stale observations, sudden record-count drops, and unexpected units."""
        now_utc = datetime.now(timezone.utc)
        stale_threshold = now_utc - timedelta(hours=24)

        # 1. Stale stations check (> 24 hours without observations)
        stale_stations = []
        locations = session.query(Location).all()
        for loc in locations:
            latest = (
                session.query(func.max(Measurement.measured_at_utc))
                .filter(Measurement.location_id == loc.id)
                .scalar()
            )
            if latest is None:
                stale_stations.append({
                    "id": loc.id,
                    "name": loc.name,
                    "reason": "No observations",
                })
            else:
                if latest.tzinfo is None:
                    latest = latest.replace(tzinfo=timezone.utc)
                if latest < stale_threshold:
                    diff_h = (now_utc - latest).total_seconds() / 3600.0
                    stale_stations.append({
                        "id": loc.id,
                        "name": loc.name,
                        "reason": f"Last data {diff_h:.1f}h ago",
                    })

        # 2. Sudden record-count drop check (> 50% drop compared to past completed runs)
        past_runs = (
            session.query(IngestionRun.rows_received)
            .filter(
                IngestionRun.status == "completed",
                IngestionRun.rows_received > 0,
            )
            .order_by(IngestionRun.started_at.desc())
            .limit(5)
            .all()
        )

        drop_warning = None
        if len(past_runs) >= 2:
            avg_rows = sum(r[0] for r in past_runs) / len(past_runs)
            if current_rows < 0.5 * avg_rows:
                drop_warning = (
                    f"Sudden record-count drop: received {current_rows} rows vs "
                    f"historical average of {round(avg_rows, 1)} (drop > 50%)"
                )

        # 3. Unexpected units check
        STANDARD_UNITS = {
            "µg/m³", "ug/m3", "ppb", "ppm", "c", "deg c", "°c",
            "%", "percent", "m/s", "deg", "particles/cm³", "particles/cm3",
        }
        sensors = session.query(Sensor).all()
        unexpected_units = []
        for s in sensors:
            u = (s.unit or "").strip().lower()
            if u and u not in STANDARD_UNITS:
                unexpected_units.append({
                    "sensor_id": s.id,
                    "parameter": s.parameter,
                    "unit": s.unit,
                })

        return {
            "stale_stations_count": len(stale_stations),
            "stale_stations": stale_stations[:10],
            "drop_warning": drop_warning,
            "unexpected_units_count": len(unexpected_units),
            "unexpected_units": unexpected_units[:10],
        }
