"""OpenAQ v3 coverage check script for Hyderabad, Telangana.

Queries OpenAQ v3 API to locate monitoring stations and sensors in and around
Hyderabad, reporting coordinates, available sensors, parameters, units,
first and last measurement dates, and whether data is recent.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests


def load_dotenv(filepath: str = ".env") -> None:
    """Simple .env loader without external dependencies."""
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    os.environ.setdefault(k, v)


BASE_URL = "https://api.openaq.org/v3"


def get_headers(api_key: str) -> Dict[str, str]:
    return {
        "X-API-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "HyderabadAirQualityCoverageCheck/1.0",
    }


def fetch_locations_bbox(
    api_key: str,
    bbox: str,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Fetch locations within a bounding box handling pagination and rate limits."""
    headers = get_headers(api_key)
    locations: List[Dict[str, Any]] = []
    page = 1

    while True:
        url = f"{BASE_URL}/locations"
        params = {
            "bbox": bbox,
            "limit": limit,
            "page": page,
        }

        retries = 3
        backoff = 2
        resp = None

        for attempt in range(retries):
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=15)
                if resp.status_code == 429:
                    wait_time = int(resp.headers.get("Retry-After", backoff))
                    print(f"Rate limited (429). Retrying after {wait_time}s...")
                    time.sleep(wait_time)
                    backoff *= 2
                    continue
                resp.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                if attempt == retries - 1:
                    print(f"Failed to fetch locations page {page}: {e}")
                    raise
                time.sleep(backoff)
                backoff *= 2

        if resp is None:
            break

        data = resp.json()
        results = data.get("results", [])
        if not results:
            break

        locations.extend(results)

        meta = data.get("meta", {})
        found = meta.get("found", 0)
        # Check if more pages exist
        if len(locations) >= found or len(results) < limit:
            break

        page += 1
        time.sleep(0.2)  # courteous delay between requests

    return locations


def fetch_location_details(api_key: str, location_id: int) -> Dict[str, Any]:
    """Fetch detailed location information including sensors."""
    headers = get_headers(api_key)
    url = f"{BASE_URL}/locations/{location_id}"
    retries = 3
    backoff = 2

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 429:
                wait_time = int(resp.headers.get("Retry-After", backoff))
                time.sleep(wait_time)
                backoff *= 2
                continue
            resp.raise_for_status()
            return resp.json().get("results", [{}])[0]
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                print(f"Error fetching location {location_id}: {e}")
                raise
            time.sleep(backoff)
            backoff *= 2
    return {}


def fetch_location_sensors(api_key: str, location_id: int) -> List[Dict[str, Any]]:
    """Fetch sensors for a given location."""
    headers = get_headers(api_key)
    url = f"{BASE_URL}/locations/{location_id}/sensors"
    retries = 3
    backoff = 2

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 429:
                wait_time = int(resp.headers.get("Retry-After", backoff))
                time.sleep(wait_time)
                backoff *= 2
                continue
            resp.raise_for_status()
            return resp.json().get("results", [])
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                print(f"Error fetching sensors for location {location_id}: {e}")
                return []
            time.sleep(backoff)
            backoff *= 2
    return []


def is_data_recent(last_datetime_str: Optional[str], days_threshold: int = 7) -> str:
    """Determine if the last measurement timestamp is recent (within threshold days)."""
    if not last_datetime_str:
        return "No Date"
    try:
        # Handle ISO format with Z or timezone offset
        dt_str = last_datetime_str.replace("Z", "+00:00")
        last_dt = datetime.fromisoformat(dt_str)
        now_utc = datetime.now(timezone.utc)
        delta_days = (now_utc - last_dt).total_seconds() / 86400.0
        if delta_days <= 2:
            return f"Active ({delta_days:.1f}d ago)"
        elif delta_days <= days_threshold:
            return f"Recent ({delta_days:.1f}d ago)"
        else:
            return f"Stale ({delta_days:.0f}d ago)"
    except Exception:
        return last_datetime_str


def main():
    load_dotenv()
    api_key = os.environ.get("OPENAQ_API_KEY")
    if not api_key:
        print("ERROR: OPENAQ_API_KEY environment variable is not set.", file=sys.stderr)
        print("Please set OPENAQ_API_KEY in your environment or in a .env file.", file=sys.stderr)
        sys.exit(1)

    print("Fetching locations around Hyderabad, Telangana from OpenAQ v3 API...")

    # Bounding box for Greater Hyderabad and surrounding areas
    # min_lon, min_lat, max_lon, max_lat
    # Hyderabad center is approx 17.3850 N, 78.4867 E
    # We search lon: [78.10, 78.80], lat: [17.10, 17.70]
    hyderabad_bbox = "78.10,17.10,78.80,17.70"

    locations = fetch_locations_bbox(api_key, hyderabad_bbox)
    print(f"Found {len(locations)} location(s) in bounding box [{hyderabad_bbox}].\n")

    if not locations:
        # Try a slightly wider Telangana region or search by coordinates
        print("Attempting point-and-radius search (25km from Hyderabad center)...")
        headers = get_headers(api_key)
        resp = requests.get(
            f"{BASE_URL}/locations",
            headers=headers,
            params={"coordinates": "17.3850,78.4867", "radius": 25000, "limit": 100},
            timeout=15,
        )
        if resp.ok:
            locations = resp.json().get("results", [])
            print(f"Found {len(locations)} location(s) within 25km radius.\n")

    summary_rows = []

    for loc in locations:
        loc_id = loc.get("id")
        loc_name = loc.get("name", "Unknown")
        coords = loc.get("coordinates") or {}
        lat = coords.get("latitude")
        lon = coords.get("longitude")
        coord_str = f"{lat:.4f}, {lon:.4f}" if lat is not None and lon is not None else "N/A"

        # Check sensors attached to location or fetch from endpoint
        sensors = loc.get("sensors", [])
        if not sensors:
            time.sleep(0.15)
            sensors = fetch_location_sensors(api_key, loc_id)

        sensor_count = len(sensors)
        parameters = []
        units = []
        first_dates = []
        last_dates = []

        for s in sensors:
            param_obj = s.get("parameter") or {}
            param_name = param_obj.get("name") or s.get("name", "")
            param_unit = param_obj.get("units") or ""
            if param_name and param_name not in parameters:
                parameters.append(param_name)
            if param_unit and param_unit not in units:
                units.append(param_unit)

            dt_first = s.get("datetimeFirst") or {}
            dt_last = s.get("datetimeLast") or {}
            first_utc = dt_first.get("utc") if isinstance(dt_first, dict) else None
            last_utc = dt_last.get("utc") if isinstance(dt_last, dict) else None
            if first_utc:
                first_dates.append(first_utc)
            if last_utc:
                last_dates.append(last_utc)

        # Location-level dates fallback
        loc_first = loc.get("datetimeFirst")
        loc_last = loc.get("datetimeLast")
        if isinstance(loc_first, dict):
            loc_first = loc_first.get("utc")
        if isinstance(loc_last, dict):
            loc_last = loc_last.get("utc")

        earliest_date = min(first_dates) if first_dates else (loc_first or "N/A")
        latest_date = max(last_dates) if last_dates else (loc_last or "N/A")

        earliest_display = earliest_date[:10] if len(earliest_date) >= 10 else earliest_date
        latest_display = latest_date[:10] if len(latest_date) >= 10 else latest_date

        recent_status = is_data_recent(latest_date if latest_date != "N/A" else None)

        summary_rows.append({
            "Location ID": loc_id,
            "Location Name": loc_name,
            "Coordinates": coord_str,
            "Sensors Count": sensor_count,
            "Parameters": ", ".join(parameters) if parameters else "None",
            "Units": ", ".join(units) if units else "None",
            "First Date": earliest_display,
            "Last Date": latest_display,
            "Data Freshness": recent_status,
            "Raw": {
                "id": loc_id,
                "name": loc_name,
                "coordinates": coords,
                "sensors": sensors,
            }
        })

    # Save detailed JSON output for reference
    os.makedirs("data", exist_ok=True)
    with open("data/coverage_check.json", "w", encoding="utf-8") as f:
        json.dump([r["Raw"] for r in summary_rows], f, indent=2)

    # Print markdown table
    print("| Location ID | Location Name | Coordinates | Sensors | Parameters | Units | First Date | Last Date | Recent? |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in summary_rows:
        print(f"| {r['Location ID']} | {r['Location Name']} | {r['Coordinates']} | {r['Sensors Count']} | {r['Parameters']} | {r['Units']} | {r['First Date']} | {r['Last Date']} | {r['Data Freshness']} |")

    # Assess coverage
    active_count = sum(1 for r in summary_rows if "Active" in r["Data Freshness"] or "Recent" in r["Data Freshness"])
    print(f"\nTotal stations found: {len(summary_rows)}")
    print(f"Stations with recent/active data: {active_count}")


if __name__ == "__main__":
    main()
