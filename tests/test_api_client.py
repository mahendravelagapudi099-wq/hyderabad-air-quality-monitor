"""Unit tests for OpenAQ v3 API client with mocked responses."""

from unittest.mock import MagicMock, patch
import pytest
import requests

from src.api_client import (
    OpenAQAuthenticationError,
    OpenAQClient,
    OpenAQClientError,
    OpenAQRateLimitError,
)


def test_missing_api_key_raises_error():
    with pytest.raises(OpenAQAuthenticationError):
        OpenAQClient(api_key="")


@patch.object(requests.Session, "get")
def test_successful_location_query(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [{"id": 407, "name": "Zoo Park"}],
        "meta": {"found": 1},
    }
    mock_get.return_value = mock_response

    client = OpenAQClient(api_key="test_key")
    res = client.get_locations(bbox="78.1,17.1,78.8,17.7")

    assert len(res["results"]) == 1
    assert res["results"][0]["id"] == 407
    mock_get.assert_called_once()


@patch.object(requests.Session, "get")
def test_authentication_failure_401(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    mock_get.return_value = mock_response

    client = OpenAQClient(api_key="invalid_key")
    with pytest.raises(OpenAQAuthenticationError):
        client.get_locations()


@patch.object(requests.Session, "get")
@patch("time.sleep", return_value=None)
def test_rate_limit_retry_success(mock_sleep, mock_get):
    # First response: 429, Second response: 200
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.headers = {"Retry-After": "1"}

    resp_200 = MagicMock()
    resp_200.status_code = 200
    resp_200.json.return_value = {"results": [{"id": 1}], "meta": {"found": 1}}

    mock_get.side_effect = [resp_429, resp_200]

    client = OpenAQClient(api_key="test_key", max_retries=3)
    res = client.get_locations()

    assert len(res["results"]) == 1
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once()
