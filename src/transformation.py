"""Transformation and normalization logic for air quality data."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import dateutil.parser


def normalize_unit_string(unit: str) -> str:
    """Normalize unit string representations for display and consistency."""
    if not unit:
        return "unknown"
    u = unit.strip()
    if u in ("ug/m3", "µg/m³", "g/m", "\u00b5g/m\u00b3", "ug/m^3"):
        return "µg/m³"
    if u.lower() in ("c", "deg c", "degree celsius", "deg_c", "°c"):
        return "°C"
    if u.lower() in ("deg", "degrees", "degree"):
        return "deg"
    if u.lower() in ("percent", "%"):
        return "%"
    if u.lower() in ("m/s", "meter/second", "ms-1"):
        return "m/s"
    if u.lower() in ("ppb", "parts per billion"):
        return "ppb"
    if u.lower() in ("ppm", "parts per million"):
        return "ppm"
    return u


def parse_utc_timestamp(dt_str: str) -> datetime:
    """Parse an ISO timestamp and return timezone-aware UTC datetime."""
    dt = dateutil.parser.isoparse(dt_str)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def transform_raw_measurement(
    raw: Dict[str, Any],
    sensor_id: int,
    location_id: int,
    param_fallback: str = "",
    unit_fallback: str = "",
) -> Dict[str, Any]:
    """Transform a validated raw OpenAQ measurement record into the schema format.

    Maintains:
    - value_original & unit_original
    - value (normalized) & unit (normalized)
    - measured_at_utc (UTC timezone-aware datetime)
    - quality_flag ('valid' or 'flagged')
    """
    raw_val = float(raw["value"])
    param_obj = raw.get("parameter") or {}
    if isinstance(param_obj, dict):
        param_name = param_obj.get("name") or param_fallback
        raw_unit = param_obj.get("units") or unit_fallback
    else:
        param_name = str(param_obj) or param_fallback
        raw_unit = raw.get("unit") or unit_fallback

    # Extract timestamp from period.datetimeTo.utc or datetime.utc
    period = raw.get("period") or {}
    dt_to = period.get("datetimeTo") or raw.get("datetime")
    if isinstance(dt_to, dict):
        dt_str = dt_to.get("utc")
    else:
        dt_str = dt_to

    measured_at_utc = parse_utc_timestamp(str(dt_str))
    norm_unit = normalize_unit_string(raw_unit)

    # Flag info from upstream if present
    flag_info = raw.get("flagInfo") or {}
    quality_flag = "flagged" if flag_info.get("hasFlags") else "valid"

    return {
        "sensor_id": sensor_id,
        "location_id": location_id,
        "parameter": param_name.lower().replace(".", ""),
        "value": raw_val,
        "unit": norm_unit,
        "value_original": raw_val,
        "unit_original": raw_unit,
        "measured_at_utc": measured_at_utc,
        "ingested_at_utc": datetime.now(timezone.utc),
        "source": "openaq_v3",
        "quality_flag": quality_flag,
    }
