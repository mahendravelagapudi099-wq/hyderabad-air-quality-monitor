"""Migration script to copy data from SQLite to PostgreSQL.

Copies all tables (locations, sensors, measurements, ingestion_runs, anomalies)
in batches, is completely idempotent and safe to re-run, and reports row counts
before and after.
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import sessionmaker

from src.config import settings
from src.models import Anomaly, Base, IngestionRun, Location, Measurement, Sensor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("sqlite_to_postgres_migration")


def get_table_counts(engine) -> Dict[str, int]:
    """Get count of rows for each model table."""
    counts = {}
    with engine.connect() as conn:
        for model in [Location, Sensor, Measurement, IngestionRun, Anomaly]:
            tbl = model.__tablename__
            try:
                cnt = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
                counts[tbl] = cnt or 0
            except Exception:
                counts[tbl] = 0
    return counts


def migrate_locations(sqlite_session, pg_session, batch_size: int = 500) -> int:
    """Migrate locations table."""
    query = sqlite_session.query(Location)
    total = query.count()
    migrated = 0

    for offset in range(0, total, batch_size):
        batch = query.offset(offset).limit(batch_size).all()
        if not batch:
            break
        records = [
            {
                "id": r.id,
                "name": r.name,
                "latitude": r.latitude,
                "longitude": r.longitude,
                "country": r.country,
                "timezone": r.timezone,
                "owner_name": r.owner_name,
                "source_metadata": r.source_metadata,
                "created_at_utc": r.created_at_utc,
            }
            for r in batch
        ]
        stmt = pg_insert(Location).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "name": stmt.excluded.name,
                "latitude": stmt.excluded.latitude,
                "longitude": stmt.excluded.longitude,
                "country": stmt.excluded.country,
                "timezone": stmt.excluded.timezone,
                "owner_name": stmt.excluded.owner_name,
                "source_metadata": stmt.excluded.source_metadata,
            },
        )
        pg_session.execute(stmt)
        pg_session.commit()
        migrated += len(batch)

    return migrated


def migrate_sensors(sqlite_session, pg_session, batch_size: int = 500) -> int:
    """Migrate sensors table."""
    query = sqlite_session.query(Sensor)
    total = query.count()
    migrated = 0

    for offset in range(0, total, batch_size):
        batch = query.offset(offset).limit(batch_size).all()
        if not batch:
            break
        records = [
            {
                "id": r.id,
                "location_id": r.location_id,
                "parameter": r.parameter,
                "unit": r.unit,
                "display_name": r.display_name,
            }
            for r in batch
        ]
        stmt = pg_insert(Sensor).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "location_id": stmt.excluded.location_id,
                "parameter": stmt.excluded.parameter,
                "unit": stmt.excluded.unit,
                "display_name": stmt.excluded.display_name,
            },
        )
        pg_session.execute(stmt)
        pg_session.commit()
        migrated += len(batch)

    return migrated


def migrate_ingestion_runs(sqlite_session, pg_session, batch_size: int = 500) -> int:
    """Migrate ingestion_runs table."""
    query = sqlite_session.query(IngestionRun)
    total = query.count()
    migrated = 0

    for offset in range(0, total, batch_size):
        batch = query.offset(offset).limit(batch_size).all()
        if not batch:
            break
        records = [
            {
                "id": r.id,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "status": r.status,
                "requests_made": r.requests_made,
                "rows_received": r.rows_received,
                "rows_inserted": r.rows_inserted,
                "rows_updated": r.rows_updated,
                "rows_rejected": r.rows_rejected,
                "error_message": r.error_message,
            }
            for r in batch
        ]
        stmt = pg_insert(IngestionRun).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "finished_at": stmt.excluded.finished_at,
                "status": stmt.excluded.status,
                "requests_made": stmt.excluded.requests_made,
                "rows_received": stmt.excluded.rows_received,
                "rows_inserted": stmt.excluded.rows_inserted,
                "rows_updated": stmt.excluded.rows_updated,
                "rows_rejected": stmt.excluded.rows_rejected,
                "error_message": stmt.excluded.error_message,
            },
        )
        pg_session.execute(stmt)
        pg_session.commit()
        migrated += len(batch)

    return migrated


def migrate_measurements(sqlite_session, pg_session, batch_size: int = 1000) -> int:
    """Migrate measurements table in batches."""
    query = sqlite_session.query(Measurement)
    total = query.count()
    migrated = 0

    for offset in range(0, total, batch_size):
        batch = query.offset(offset).limit(batch_size).all()
        if not batch:
            break
        records = [
            {
                "sensor_id": r.sensor_id,
                "location_id": r.location_id,
                "parameter": r.parameter,
                "value": r.value,
                "unit": r.unit,
                "value_original": r.value_original,
                "unit_original": r.unit_original,
                "measured_at_utc": r.measured_at_utc,
                "ingested_at_utc": r.ingested_at_utc,
                "source": r.source,
                "quality_flag": r.quality_flag,
            }
            for r in batch
        ]
        stmt = pg_insert(Measurement).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["sensor_id", "parameter", "measured_at_utc"],
            set_={
                "value": stmt.excluded.value,
                "unit": stmt.excluded.unit,
                "value_original": stmt.excluded.value_original,
                "unit_original": stmt.excluded.unit_original,
                "ingested_at_utc": stmt.excluded.ingested_at_utc,
                "quality_flag": stmt.excluded.quality_flag,
                "source": stmt.excluded.source,
            },
        )
        pg_session.execute(stmt)
        pg_session.commit()
        migrated += len(batch)
        if migrated % 5000 == 0 or migrated == total:
            logger.info("  ...migrated %d / %d measurement records", migrated, total)

    return migrated


def migrate_anomalies(sqlite_session, pg_session, batch_size: int = 500) -> int:
    """Migrate anomalies table."""
    query = sqlite_session.query(Anomaly)
    total = query.count()
    migrated = 0

    for offset in range(0, total, batch_size):
        batch = query.offset(offset).limit(batch_size).all()
        if not batch:
            break
        records = [
            {
                "sensor_id": r.sensor_id,
                "location_id": r.location_id,
                "parameter": r.parameter,
                "measured_at_utc": r.measured_at_utc,
                "observed_value": r.observed_value,
                "baseline_median": r.baseline_median,
                "expected_low": r.expected_low,
                "expected_high": r.expected_high,
                "method": r.method,
                "severity": r.severity,
                "detected_at_utc": r.detected_at_utc,
            }
            for r in batch
        ]
        stmt = pg_insert(Anomaly).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=["sensor_id", "parameter", "measured_at_utc"],
            set_={
                "observed_value": stmt.excluded.observed_value,
                "baseline_median": stmt.excluded.baseline_median,
                "expected_low": stmt.excluded.expected_low,
                "expected_high": stmt.excluded.expected_high,
                "method": stmt.excluded.method,
                "severity": stmt.excluded.severity,
            },
        )
        pg_session.execute(stmt)
        pg_session.commit()
        migrated += len(batch)

    return migrated


def sync_postgres_sequences(pg_engine) -> None:
    """Sync primary key serial sequences in PostgreSQL to prevent duplicate key errors on future inserts."""
    with pg_engine.connect() as conn:
        for table, col in [
            ("measurements", "id"),
            ("ingestion_runs", "id"),
            ("anomalies", "id"),
        ]:
            try:
                conn.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', '{col}'), "
                        f"COALESCE(MAX({col}), 1)) FROM {table};"
                    )
                )
                conn.commit()
            except Exception as e:
                logger.debug("Sequence update for %s skipped: %s", table, e)


def main():
    parser = argparse.ArgumentParser(
        description="Migrate all data from SQLite data/airquality.db to PostgreSQL."
    )
    parser.add_argument(
        "--sqlite-path",
        default="data/airquality.db",
        help="Path to source SQLite database (default: data/airquality.db)",
    )
    parser.add_argument(
        "--target-url",
        default=None,
        help="Target PostgreSQL connection string (defaults to TARGET_DATABASE_URL or DATABASE_URL env var)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for measurement inserts (default: 1000)",
    )
    args = parser.parse_args()

    sqlite_file = Path(args.sqlite_path)
    if not sqlite_file.exists():
        logger.error("Source SQLite database file '%s' does not exist.", sqlite_file)
        sys.exit(1)

    pg_url = (
        args.target_url
        or os.getenv("TARGET_DATABASE_URL")
        or os.getenv("DATABASE_URL")
    )
    if not pg_url or not (pg_url.startswith("postgres://") or pg_url.startswith("postgresql://")):
        logger.error(
            "A valid PostgreSQL connection string must be provided via --target-url, "
            "TARGET_DATABASE_URL, or DATABASE_URL."
        )
        sys.exit(1)

    if pg_url.startswith("postgres://"):
        pg_url = pg_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif pg_url.startswith("postgresql://") and not pg_url.startswith("postgresql+"):
        pg_url = pg_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    logger.info("Source SQLite: %s", sqlite_file)
    # Mask password for secure logging
    safe_pg_url = pg_url.split("@")[-1] if "@" in pg_url else "postgres"
    logger.info("Target PostgreSQL: ...@%s", safe_pg_url)

    # Initialize engines & sessions
    sqlite_engine = create_engine(f"sqlite:///{sqlite_file}")
    pg_engine = create_engine(pg_url, pool_pre_ping=True)

    # Create tables on Postgres if not already present
    logger.info("Ensuring schema exists on target PostgreSQL database...")
    Base.metadata.create_all(bind=pg_engine)

    # Pre-migration row counts
    sqlite_counts = get_table_counts(sqlite_engine)
    pg_counts_before = get_table_counts(pg_engine)

    print("\n" + "=" * 65)
    print("PRE-MIGRATION ROW COUNTS")
    print("=" * 65)
    print(f"{'Table':<20} | {'Source (SQLite)':<18} | {'Target (Postgres Before)':<22}")
    print("-" * 65)
    for tbl in ["locations", "sensors", "ingestion_runs", "measurements", "anomalies"]:
        print(f"{tbl:<20} | {sqlite_counts.get(tbl, 0):<18} | {pg_counts_before.get(tbl, 0):<22}")
    print("=" * 65 + "\n")

    SqliteSession = sessionmaker(bind=sqlite_engine)
    PgSession = sessionmaker(bind=pg_engine)

    sqlite_sess = SqliteSession()
    pg_sess = PgSession()

    try:
        logger.info("Migrating locations...")
        loc_migrated = migrate_locations(sqlite_sess, pg_sess)
        logger.info("Migrated %d locations.", loc_migrated)

        logger.info("Migrating sensors...")
        sensor_migrated = migrate_sensors(sqlite_sess, pg_sess)
        logger.info("Migrated %d sensors.", sensor_migrated)

        logger.info("Migrating ingestion runs...")
        runs_migrated = migrate_ingestion_runs(sqlite_sess, pg_sess)
        logger.info("Migrated %d ingestion runs.", runs_migrated)

        logger.info("Migrating measurements in batches of %d...", args.batch_size)
        meas_migrated = migrate_measurements(sqlite_sess, pg_sess, batch_size=args.batch_size)
        logger.info("Migrated %d measurements.", meas_migrated)

        logger.info("Migrating anomalies...")
        anom_migrated = migrate_anomalies(sqlite_sess, pg_sess)
        logger.info("Migrated %d anomalies.", anom_migrated)

        # Synchronize Postgres serial sequences
        sync_postgres_sequences(pg_engine)

    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        sqlite_sess.close()
        pg_sess.close()

    # Post-migration row counts
    pg_counts_after = get_table_counts(pg_engine)

    print("\n" + "=" * 65)
    print("POST-MIGRATION ROW COUNTS")
    print("=" * 65)
    print(f"{'Table':<20} | {'Source (SQLite)':<18} | {'Target (Postgres After)':<22}")
    print("-" * 65)
    for tbl in ["locations", "sensors", "ingestion_runs", "measurements", "anomalies"]:
        print(f"{tbl:<20} | {sqlite_counts.get(tbl, 0):<18} | {pg_counts_after.get(tbl, 0):<22}")
    print("=" * 65 + "\n")
    logger.info("Migration completed successfully!")


if __name__ == "__main__":
    main()
