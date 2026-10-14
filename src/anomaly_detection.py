"""Statistical anomaly detection using rolling Median and Median Absolute Deviation (MAD)."""

import logging
from datetime import datetime, timezone
from typing import List, Optional
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from src.config import settings
from src.models import Anomaly, Measurement, Sensor

logger = logging.getLogger(__name__)


def compute_mad(values: np.ndarray) -> float:
    """Compute Median Absolute Deviation (MAD)."""
    median = np.median(values)
    return float(np.median(np.abs(values - median)))


def detect_anomalies_for_sensor(
    session: Session,
    sensor_id: int,
    min_observations: int = 48,
    threshold_factor: float = 3.5,
) -> List[Anomaly]:
    """Detect statistical anomalies for a given sensor using rolling Median and MAD.

    Requires at least min_observations before flagging.
    Stores baseline median, expected low, expected high, and severity.
    """
    # Fetch chronological measurements for this sensor
    records = (
        session.query(Measurement)
        .filter(Measurement.sensor_id == sensor_id)
        .order_by(Measurement.measured_at_utc.asc())
        .all()
    )

    if len(records) < min_observations:
        logger.debug(
            "Sensor %d has %d observations (< %d required). Skipping anomaly check.",
            sensor_id, len(records), min_observations
        )
        return []

    # Convert to DataFrame
    data = [
        {
            "id": r.id,
            "sensor_id": r.sensor_id,
            "location_id": r.location_id,
            "parameter": r.parameter,
            "value": r.value,
            "measured_at_utc": r.measured_at_utc,
        }
        for r in records
    ]
    df = pd.DataFrame(data)

    new_anomalies: List[Anomaly] = []

    # Use rolling window (e.g., 48 observations)
    window = min_observations
    vals = df["value"].values

    for i in range(window, len(df)):
        window_vals = vals[max(0, i - window):i]
        curr_val = vals[i]
        curr_rec = df.iloc[i]

        median_val = float(np.median(window_vals))
        mad_val = compute_mad(window_vals)

        # Scale factor for normal distribution consistency ~ 1.4826
        scaled_mad = 1.4826 * mad_val

        # If scaled_mad is 0 (flat values), use 10% of median or 1.0 as minimal noise floor
        if scaled_mad < 1e-4:
            scaled_mad = max(0.1 * abs(median_val), 1.0)

        expected_low = max(0.0, median_val - (threshold_factor * scaled_mad))
        expected_high = median_val + (threshold_factor * scaled_mad)

        if curr_val < expected_low or curr_val > expected_high:
            # Check distance for severity
            distance = abs(curr_val - median_val) / scaled_mad
            severity = "high" if distance >= 5.0 else ("medium" if distance >= 4.0 else "low")

            # Check if this anomaly is already recorded
            existing = (
                session.query(Anomaly)
                .filter(
                    Anomaly.sensor_id == int(curr_rec["sensor_id"]),
                    Anomaly.parameter == str(curr_rec["parameter"]),
                    Anomaly.measured_at_utc == curr_rec["measured_at_utc"],
                )
                .first()
            )

            if not existing:
                anomaly = Anomaly(
                    sensor_id=int(curr_rec["sensor_id"]),
                    location_id=int(curr_rec["location_id"]),
                    parameter=str(curr_rec["parameter"]),
                    measured_at_utc=curr_rec["measured_at_utc"],
                    observed_value=float(curr_val),
                    baseline_median=round(median_val, 2),
                    expected_low=round(expected_low, 2),
                    expected_high=round(expected_high, 2),
                    method=f"rolling_mad_{threshold_factor}",
                    severity=severity,
                    detected_at_utc=datetime.now(timezone.utc),
                )
                new_anomalies.append(anomaly)
                session.add(anomaly)

    return new_anomalies


def run_anomaly_detection_pipeline(session: Session) -> int:
    """Run anomaly detection across all active sensors in the database.

    Returns:
        total new anomalies flagged
    """
    sensors = session.query(Sensor).all()
    total_flagged = 0

    for s in sensors:
        anomalies = detect_anomalies_for_sensor(
            session=session,
            sensor_id=s.id,
            min_observations=settings.MIN_OBSERVATIONS_FOR_ANOMALY,
            threshold_factor=settings.MAD_THRESHOLD,
        )
        total_flagged += len(anomalies)

    session.flush()
    return total_flagged
