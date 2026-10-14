"""Optional live API smoke test running only when OPENAQ_API_KEY is configured."""

import os
import pytest
from src.api_client import OpenAQClient
from src.config import settings


@pytest.mark.skipif(
    not settings.OPENAQ_API_KEY,
    reason="OPENAQ_API_KEY is not configured. Skipping live API smoke test.",
)
def test_live_api_smoke_locations():
    """Verify live connectivity and location fetching from OpenAQ v3 API."""
    client = OpenAQClient(api_key=settings.OPENAQ_API_KEY)
    # Query Hyderabad with limit 2
    data = client.get_locations(bbox=settings.HYDERABAD_BBOX, limit=2)
    assert "results" in data
    assert len(data["results"]) >= 1
    first_loc = data["results"][0]
    assert "id" in first_loc
    assert "name" in first_loc
