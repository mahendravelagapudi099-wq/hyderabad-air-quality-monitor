"""Database connection, session management, and idempotent upsert helpers."""

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import settings
from src.models import Base, Location, Sensor, Measurement, IngestionRun, Anomaly


def create_db_engine(url: Optional[str] = None) -> Engine:
    """Create SQLAlchemy engine with appropriate configurations for SQLite or PostgreSQL."""
    db_url = url or settings.DATABASE_URL
    is_sqlite = db_url.startswith("sqlite")

    engine = create_engine(
        db_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )

    if is_sqlite:
        # Enable Foreign Key support and WAL mode for SQLite
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


# Global engine and sessionmaker
engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)


def init_db(target_engine: Optional[Engine] = None) -> None:
    """Create all database tables."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)


@contextmanager
def get_session(session_factory=SessionLocal) -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def upsert_location(session: Session, loc_data: Dict[str, Any]) -> Tuple[Location, bool]:
    """Upsert a Location record. Returns (location, was_created)."""
    loc_id = loc_data["id"]
    existing = session.query(Location).filter(Location.id == loc_id).first()
    if existing:
        existing.name = loc_data.get("name", existing.name)
        existing.latitude = loc_data.get("latitude", existing.latitude)
        existing.longitude = loc_data.get("longitude", existing.longitude)
        existing.country = loc_data.get("country", existing.country)
        existing.timezone = loc_data.get("timezone", existing.timezone)
        existing.owner_name = loc_data.get("owner_name", existing.owner_name)
        existing.source_metadata = loc_data.get("source_metadata", existing.source_metadata)
        return existing, False

    new_loc = Location(
        id=loc_id,
        name=loc_data["name"],
        latitude=loc_data["latitude"],
        longitude=loc_data["longitude"],
        country=loc_data.get("country", "IN"),
        timezone=loc_data.get("timezone", "Asia/Kolkata"),
        owner_name=loc_data.get("owner_name"),
        source_metadata=loc_data.get("source_metadata"),
        created_at_utc=datetime.now(timezone.utc),
    )
    session.add(new_loc)
    return new_loc, True


def upsert_sensor(session: Session, sensor_data: Dict[str, Any]) -> Tuple[Sensor, bool]:
    """Upsert a Sensor record. Returns (sensor, was_created)."""
    sensor_id = sensor_data["id"]
    existing = session.query(Sensor).filter(Sensor.id == sensor_id).first()
    if existing:
        existing.parameter = sensor_data.get("parameter", existing.parameter)
        existing.unit = sensor_data.get("unit", existing.unit)
        existing.display_name = sensor_data.get("display_name", existing.display_name)
        return existing, False

    new_sensor = Sensor(
        id=sensor_id,
        location_id=sensor_data["location_id"],
        parameter=sensor_data["parameter"],
        unit=sensor_data["unit"],
        display_name=sensor_data.get("display_name"),
    )
    session.add(new_sensor)
    return new_sensor, True


def bulk_upsert_measurements(
    session: Session,
    records: List[Dict[str, Any]],
) -> Tuple[int, int]:
    """Bulk upsert measurements idempotently.

    Returns:
        (rows_inserted, rows_updated)
    """
    if not records:
        return 0, 0

    dialect_name = session.bind.dialect.name
    now_utc = datetime.now(timezone.utc)

    # Ensure ingested_at_utc is set
    for r in records:
        if "ingested_at_utc" not in r:
            r["ingested_at_utc"] = now_utc

    if dialect_name == "sqlite":
        # SQLite native ON CONFLICT upsert
        stmt = sqlite_insert(Measurement).values(records)
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
        result = session.execute(stmt)
        # In SQLite, rowcount reflects total affected rows
        inserted_count = len(records)
        return inserted_count, 0

    elif dialect_name == "postgresql":
        # PostgreSQL native ON CONFLICT upsert
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
        session.execute(stmt)
        return len(records), 0

    else:
        # Fallback for generic SQL: check existing keys
        inserted = 0
        updated = 0
        for r in records:
            existing = (
                session.query(Measurement)
                .filter(
                    Measurement.sensor_id == r["sensor_id"],
                    Measurement.parameter == r["parameter"],
                    Measurement.measured_at_utc == r["measured_at_utc"],
                )
                .first()
            )
            if existing:
                existing.value = r["value"]
                existing.unit = r["unit"]
                existing.value_original = r["value_original"]
                existing.unit_original = r["unit_original"]
                existing.ingested_at_utc = r["ingested_at_utc"]
                existing.quality_flag = r.get("quality_flag", "valid")
                updated += 1
            else:
                m = Measurement(**r)
                session.add(m)
                inserted += 1
        return inserted, updated
