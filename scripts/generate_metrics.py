"""Generate truthful project metrics directly from the live database.

Queries the active database (PostgreSQL or SQLite) and prints verified metrics:
- Stations monitored
- Records collected
- Days of history
- Missing-data / rejection rate
- Anomalies detected
- Ingestion workflow runs and success rate
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func
from src.config import settings
from src.database import create_db_engine, get_session
from src.models import Anomaly, IngestionRun, Location, Measurement, Sensor


def generate_metrics(db_url: str = None) -> dict:
    url = db_url or settings.DATABASE_URL
    engine = create_db_engine(url)

    with get_session() as session:
        stations_monitored = session.query(func.count(Location.id)).scalar() or 0
        sensors_count = session.query(func.count(Sensor.id)).scalar() or 0
        records_collected = session.query(func.count(Measurement.id)).scalar() or 0
        anomalies_detected = session.query(func.count(Anomaly.id)).scalar() or 0

        first_date = session.query(func.min(Measurement.measured_at_utc)).scalar()
        last_date = session.query(func.max(Measurement.measured_at_utc)).scalar()

        if first_date and last_date:
            days_of_history = round((last_date - first_date).total_seconds() / 86400.0, 1)
            time_range_str = f"{first_date.strftime('%Y-%m-%d %H:%M UTC')} to {last_date.strftime('%Y-%m-%d %H:%M UTC')} ({days_of_history} days)"
        else:
            days_of_history = 0.0
            time_range_str = "No records"

        runs = session.query(IngestionRun).all()
        total_runs = len(runs)
        completed_runs = sum(1 for r in runs if r.status == "completed")
        success_rate = (completed_runs / total_runs * 100.0) if total_runs > 0 else 100.0

        total_received = sum(r.rows_received for r in runs)
        total_rejected = sum(r.rows_rejected for r in runs)
        rejection_rate = (total_rejected / total_received * 100.0) if total_received > 0 else 0.0

    return {
        "database_target": "PostgreSQL" if "postgres" in url else "SQLite",
        "stations_monitored": stations_monitored,
        "sensors_count": sensors_count,
        "records_collected": records_collected,
        "days_of_history": days_of_history,
        "time_range": time_range_str,
        "total_received": total_received,
        "rejection_rate": round(rejection_rate, 2),
        "anomalies_detected": anomalies_detected,
        "workflow_runs": total_runs,
        "workflow_success_rate": round(success_rate, 1),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate verified metrics from the database.")
    parser.add_argument("--db-url", default=None, help="Optional database URL override.")
    args = parser.parse_args()

    metrics = generate_metrics(args.db_url)

    print("\n" + "=" * 65)
    print("VERIFIED PROJECT METRICS (GENERATED DIRECTLY FROM DATABASE)")
    print("=" * 65)
    print(f"Database Backend             : {metrics['database_target']}")
    print(f"Stations Monitored           : {metrics['stations_monitored']}")
    print(f"Sensors Mapped               : {metrics['sensors_count']}")
    print(f"Records Collected            : {metrics['records_collected']:,}")
    print(f"Days of History              : {metrics['days_of_history']} days ({metrics['time_range']})")
    print(f"Total Telemetry Received     : {metrics['total_received']:,}")
    print(f"Missing-Data / Rejected Rate : {metrics['rejection_rate']:.2f}%")
    print(f"Anomalies Detected (MAD>3.5) : {metrics['anomalies_detected']}")
    print(f"Workflow Executions          : {metrics['workflow_runs']}")
    print(f"Workflow Success Rate        : {metrics['workflow_success_rate']:.1f}%")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
