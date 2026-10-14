"""OpenAQ API v3 client with rate-limiting, backoff, and pagination."""

import logging
import time
from typing import Any, Dict, List, Optional
import requests

from src.config import settings

logger = logging.getLogger(__name__)


class OpenAQClientError(Exception):
    """Base exception for OpenAQ API errors."""
    pass


class OpenAQAuthenticationError(OpenAQClientError):
    """Raised when API key is missing or invalid (401/403)."""
    pass


class OpenAQRateLimitError(OpenAQClientError):
    """Raised when rate limit is exceeded and all retries are exhausted."""
    pass


class OpenAQClient:
    """Client for OpenAQ API v3."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        max_retries: Optional[int] = None,
        backoff_factor: Optional[float] = None,
    ):
        self.api_key = settings.OPENAQ_API_KEY if api_key is None else api_key
        if not self.api_key:
            raise OpenAQAuthenticationError(
                "OPENAQ_API_KEY is missing. An API key is required to query OpenAQ v3."
            )

        self.base_url = (base_url or settings.OPENAQ_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.API_TIMEOUT_SECONDS
        self.max_retries = max_retries or settings.MAX_RETRIES
        self.backoff_factor = backoff_factor or settings.BACKOFF_FACTOR

        self.session = requests.Session()
        self.session.headers.update({
            "X-API-Key": self.api_key,
            "Accept": "application/json",
            "User-Agent": "HyderabadAirQualityMonitor/1.0",
        })
        self.requests_made = 0

    def _request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make an authenticated HTTP GET request with retries and rate limit handling."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        backoff = self.backoff_factor

        for attempt in range(1, self.max_retries + 1):
            try:
                self.requests_made += 1
                logger.debug("GET %s (attempt %d, params=%s)", url, attempt, params)
                response = self.session.get(url, params=params, timeout=self.timeout)

                if response.status_code in (401, 403):
                    raise OpenAQAuthenticationError(
                        f"Authentication failed ({response.status_code}): {response.text}"
                    )

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    sleep_time = float(retry_after) if retry_after else backoff
                    logger.warning(
                        "Rate limit hit (429) on %s. Retrying in %.1fs (attempt %d/%d)...",
                        url, sleep_time, attempt, self.max_retries
                    )
                    time.sleep(sleep_time)
                    backoff *= 2
                    continue

                if response.status_code >= 500:
                    logger.warning(
                        "Server error (%d) on %s. Retrying in %.1fs...",
                        response.status_code, url, backoff
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                response.raise_for_status()
                return response.json()

            except requests.exceptions.RequestException as e:
                if attempt == self.max_retries:
                    logger.error("Request failed after %d attempts: %s", self.max_retries, e)
                    raise OpenAQClientError(f"HTTP request failed: {e}") from e
                time.sleep(backoff)
                backoff *= 2

        raise OpenAQRateLimitError(f"Exceeded max retries for {url}")

    def get_locations(
        self,
        bbox: Optional[str] = None,
        coordinates: Optional[str] = None,
        radius: Optional[int] = None,
        limit: int = 100,
        page: int = 1,
    ) -> Dict[str, Any]:
        """Fetch locations using bbox or coordinates + radius."""
        params: Dict[str, Any] = {"limit": limit, "page": page}
        if bbox:
            params["bbox"] = bbox
        elif coordinates:
            params["coordinates"] = coordinates
            if radius:
                params["radius"] = radius
        return self._request("locations", params=params)

    def get_all_locations(
        self,
        bbox: Optional[str] = None,
        coordinates: Optional[str] = None,
        radius: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Paginate and fetch all locations in region."""
        all_locations = []
        page = 1
        limit = 100

        while True:
            data = self.get_locations(
                bbox=bbox,
                coordinates=coordinates,
                radius=radius,
                limit=limit,
                page=page,
            )
            results = data.get("results", [])
            if not results:
                break
            all_locations.extend(results)

            meta = data.get("meta", {})
            found = meta.get("found", 0)
            if len(all_locations) >= found or len(results) < limit:
                break

            page += 1
            time.sleep(0.1)

        return all_locations

    def get_location_sensors(self, location_id: int) -> List[Dict[str, Any]]:
        """Fetch all sensors for a location."""
        data = self._request(f"locations/{location_id}/sensors")
        return data.get("results", [])

    def get_sensor_measurements(
        self,
        sensor_id: int,
        datetime_from: Optional[str] = None,
        datetime_to: Optional[str] = None,
        limit: int = 100,
        page: int = 1,
    ) -> Dict[str, Any]:
        """Fetch raw measurements for a sensor."""
        params: Dict[str, Any] = {"limit": limit, "page": page}
        if datetime_from:
            params["datetime_from"] = datetime_from
        if datetime_to:
            params["datetime_to"] = datetime_to
        return self._request(f"sensors/{sensor_id}/measurements", params=params)

    def get_sensor_hours(
        self,
        sensor_id: int,
        datetime_from: Optional[str] = None,
        datetime_to: Optional[str] = None,
        limit: int = 100,
        page: int = 1,
    ) -> Dict[str, Any]:
        """Fetch precomputed hourly measurements for a sensor."""
        params: Dict[str, Any] = {"limit": limit, "page": page}
        if datetime_from:
            params["datetime_from"] = datetime_from
        if datetime_to:
            params["datetime_to"] = datetime_to
        return self._request(f"sensors/{sensor_id}/hours", params=params)
