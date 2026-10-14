"""Unit tests for data transformation and unit normalization."""

from datetime import datetime, timezone
import pytest
from src.transformation import (
    normalize_unit_string,
    parse_utc_timestamp,
    transform_raw_measurement,
)


def test_normalize_units():
    assert normalize_unit_string("ug/m3") == "µg/m³"
    assert normalize_unit_string("µg/m³") == "µg/m³"
    assert normalize_unit_string("\u00b5g/m\u00b3") == "µg/m³"
    assert normalize_unit_string("c") == "°C"
    assert normalize_unit_string("deg C") == "°C"
    assert normalize_unit_string("%") == "%"
    assert normalize_unit_string("ppb") == "ppb"
    assert normalize_unit_string("ppm") == "ppm"


def test_parse_utc_timestamp():
    dt = parse_utc_timestamp("2026-10-14T12:30:00Z")
    assert dt.tzinfo is not None
    assert dt.year == 2026
    assert dt.month == 10
    assert dt.day == 14
    assert dt.hour == 12

    # Local offset +05:30 converted to UTC
    dt_local = parse_utc_timestamp("2026-10-14T18:00:00+05:30")
    assert dt_local.hour == 12
    assert dt_local.minute == 30


def test_transform_raw_measurement():
    raw = {
        "value": 55.4,
        "parameter": {"id": 2, "name": "pm25", "units": "ug/m3"},
        "period": {
            "datetimeTo": {
                "utc": "2026-10-14T12:00:00Z",
                "local": "2026-10-14T17:30:00+05:30",
            }
        },
        "flagInfo": {"hasFlags": False},
    }

    res = transform_raw_measurement(raw, sensor_id=101, location_id=407)
    assert res["sensor_id"] == 101
    assert res["location_id"] == 407
    assert res["parameter"] == "pm25"
    assert res["value"] == 55.4
    assert res["unit"] == "µg/m³"
    assert res["value_original"] == 55.4
    assert res["unit_original"] == "ug/m3"
    assert res["measured_at_utc"] == datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    assert res["quality_flag"] == "valid"
