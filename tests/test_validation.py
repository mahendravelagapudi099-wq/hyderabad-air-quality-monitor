"""Unit tests for measurement validation logic."""

import pytest
from src.validation import validate_measurement


def test_validate_valid_measurement():
    record = {
        "value": 42.5,
        "parameter": "pm25",
        "period": {"datetimeTo": {"utc": "2026-10-14T12:00:00Z"}},
    }
    is_valid, reason = validate_measurement(record)
    assert is_valid is True
    assert reason is None


def test_validate_reject_null_value():
    record = {
        "value": None,
        "parameter": "pm25",
        "period": {"datetimeTo": {"utc": "2026-10-14T12:00:00Z"}},
    }
    is_valid, reason = validate_measurement(record)
    assert is_valid is False
    assert "Null" in reason


def test_validate_reject_missing_value():
    record = {
        "parameter": "pm25",
        "period": {"datetimeTo": {"utc": "2026-10-14T12:00:00Z"}},
    }
    is_valid, reason = validate_measurement(record)
    assert is_valid is False
    assert "Null" in reason


def test_validate_reject_negative_pollutant():
    record = {
        "value": -15.2,
        "parameter": "pm25",
        "period": {"datetimeTo": {"utc": "2026-10-14T12:00:00Z"}},
    }
    is_valid, reason = validate_measurement(record)
    assert is_valid is False
    assert "Negative" in reason


def test_validate_allow_negative_temperature():
    record = {
        "value": -2.5,
        "parameter": "temperature",
        "period": {"datetimeTo": {"utc": "2026-10-14T12:00:00Z"}},
    }
    is_valid, reason = validate_measurement(record)
    assert is_valid is True


def test_validate_reject_impossible_out_of_bounds():
    record = {
        "value": 25000.0,  # Impossible for PM2.5 (limit 1500)
        "parameter": "pm25",
        "period": {"datetimeTo": {"utc": "2026-10-14T12:00:00Z"}},
    }
    is_valid, reason = validate_measurement(record)
    assert is_valid is False
    assert "out of physical limits" in reason


def test_validate_reject_malformed_string():
    record = {
        "value": "corrupted_text",
        "parameter": "pm25",
        "period": {"datetimeTo": {"utc": "2026-10-14T12:00:00Z"}},
    }
    is_valid, reason = validate_measurement(record)
    assert is_valid is False
    assert "Malformed" in reason


def test_validate_reject_missing_timestamp():
    record = {
        "value": 35.0,
        "parameter": "pm25",
        "period": {},
    }
    is_valid, reason = validate_measurement(record)
    assert is_valid is False
    assert "timestamp" in reason.lower()
