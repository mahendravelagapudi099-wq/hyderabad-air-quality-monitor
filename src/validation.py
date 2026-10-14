"""Validation logic for raw air quality measurement records."""

import math
from typing import Any, Dict, Optional, Tuple

# Physical upper bounds for Hyderabad environmental parameters
PARAMETER_LIMITS: Dict[str, Tuple[float, float]] = {
    # parameter: (min_value, max_value) in standard units
    "pm25": (0.0, 1500.0),        # µg/m³
    "pm10": (0.0, 2000.0),        # µg/m³
    "no2": (0.0, 2000.0),         # µg/m³
    "so2": (0.0, 2500.0),         # µg/m³
    "co": (0.0, 100000.0),        # ppb or µg/m³
    "o3": (0.0, 1000.0),          # µg/m³
    "temperature": (-10.0, 60.0), # °C
    "relativehumidity": (0.0, 100.0),  # %
    "wind_speed": (0.0, 100.0),   # m/s
    "wind_direction": (0.0, 360.0), # degrees
}


def validate_measurement(
    record: Dict[str, Any],
) -> Tuple[bool, Optional[str]]:
    """Validate a raw measurement record.

    Rules:
    - Never fill missing values with zero.
    - Reject null, malformed, negative, or physically impossible values.
    - Reject records with missing or invalid timestamps.

    Returns:
        (is_valid, rejection_reason)
    """
    # 1. Check raw value existence
    if "value" not in record or record["value"] is None:
        return False, "Null value"

    val = record["value"]

    # 2. Check for numeric type and non-NaN / finite
    try:
        val_float = float(val)
    except (ValueError, TypeError):
        return False, f"Malformed non-numeric value: {val}"

    if math.isnan(val_float) or math.isinf(val_float):
        return False, f"Invalid float value: {val_float}"

    # 3. Reject negative pollutant concentrations (sensor calibration artifacts)
    param = str(record.get("parameter", "")).lower().replace(".", "")
    if param not in ("temperature", "wind_direction") and val_float < 0:
        return False, f"Negative concentration ({val_float}) rejected"

    # 4. Check physical upper and lower bounds
    if param in PARAMETER_LIMITS:
        low, high = PARAMETER_LIMITS[param]
        if val_float < low or val_float > high:
            return False, f"Value {val_float} out of physical limits [{low}, {high}] for {param}"

    # 5. Check timestamp validity
    period = record.get("period") or {}
    dt_to = period.get("datetimeTo") or record.get("datetime")
    if isinstance(dt_to, dict):
        dt_utc = dt_to.get("utc")
    else:
        dt_utc = dt_to or record.get("measured_at_utc")

    if not dt_utc:
        return False, "Missing timestamp"

    return True, None
