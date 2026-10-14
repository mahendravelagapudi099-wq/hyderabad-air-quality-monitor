"""SQLAlchemy models for Hyderabad Air Quality Monitor."""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Location(Base):
    """Monitoring station location."""

    __tablename__ = "locations"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    country = Column(String(10), default="IN")
    timezone = Column(String(50), default="Asia/Kolkata")
    owner_name = Column(String(255), nullable=True)
    source_metadata = Column(Text, nullable=True)
    created_at_utc = Column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    sensors = relationship("Sensor", back_populates="location", cascade="all, delete-orphan")
    measurements = relationship("Measurement", back_populates="location")

    def __repr__(self) -> str:
        return f"<Location(id={self.id}, name='{self.name}')>"


class Sensor(Base):
    """Specific pollutant or meteorological sensor at a location."""

    __tablename__ = "sensors"

    id = Column(Integer, primary_key=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False, index=True)
    parameter = Column(String(50), nullable=False, index=True)
    unit = Column(String(50), nullable=False)
    display_name = Column(String(100), nullable=True)

    location = relationship("Location", back_populates="sensors")
    measurements = relationship("Measurement", back_populates="sensor")
    anomalies = relationship("Anomaly", back_populates="sensor")

    def __repr__(self) -> str:
        return f"<Sensor(id={self.id}, param='{self.parameter}', loc={self.location_id})>"


class Measurement(Base):
    """Air quality measurement record with normalization and quality flag."""

    __tablename__ = "measurements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=False)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=False)
    parameter = Column(String(50), nullable=False)

    # Cleaned & Normalized values
    value = Column(Float, nullable=False)
    unit = Column(String(50), nullable=False)

    # Original upstream values preserved
    value_original = Column(Float, nullable=False)
    unit_original = Column(String(50), nullable=False)

    # Timestamps
    measured_at_utc = Column(DateTime(timezone=True), nullable=False)
    ingested_at_utc = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    source = Column(String(100), default="openaq_v3")
    quality_flag = Column(String(50), default="valid")

    # Relationships
    sensor = relationship("Sensor", back_populates="measurements")
    location = relationship("Location", back_populates="measurements")

    __table_args__ = (
        UniqueConstraint(
            "sensor_id",
            "parameter",
            "measured_at_utc",
            name="uq_sensor_param_time",
        ),
        Index("idx_measurements_time", "measured_at_utc"),
        Index("idx_measurements_loc_param", "location_id", "parameter"),
    )

    def __repr__(self) -> str:
        return (
            f"<Measurement(sensor={self.sensor_id}, {self.parameter}={self.value} {self.unit} "
            f"at {self.measured_at_utc})>"
        )


class IngestionRun(Base):
    """Audit log tracking pipeline executions, counts, and errors."""

    __tablename__ = "ingestion_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), nullable=False)  # 'in_progress', 'completed', 'failed'
    requests_made = Column(Integer, default=0)
    rows_received = Column(Integer, default=0)
    rows_inserted = Column(Integer, default=0)
    rows_updated = Column(Integer, default=0)
    rows_rejected = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<IngestionRun(id={self.id}, status='{self.status}', inserted={self.rows_inserted})>"


class Anomaly(Base):
    """Statistical anomaly detected using rolling Median and MAD."""

    __tablename__ = "anomalies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=False, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True, index=True)
    parameter = Column(String(50), nullable=False, index=True)
    measured_at_utc = Column(DateTime(timezone=True), nullable=False, index=True)
    observed_value = Column(Float, nullable=False)
    baseline_median = Column(Float, nullable=False)
    expected_low = Column(Float, nullable=False)
    expected_high = Column(Float, nullable=False)
    method = Column(String(50), default="rolling_mad_3.5")
    severity = Column(String(50), default="medium")  # 'low', 'medium', 'high'
    detected_at_utc = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    sensor = relationship("Sensor", back_populates="anomalies")

    __table_args__ = (
        UniqueConstraint(
            "sensor_id",
            "parameter",
            "measured_at_utc",
            name="uq_anomaly_record",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Anomaly(sensor={self.sensor_id}, {self.parameter}={self.observed_value} "
            f"expected [{self.expected_low:.1f}, {self.expected_high:.1f}] at {self.measured_at_utc})>"
        )
