"""Tests for niles.http_retry — tenacity-based retry decorator."""

import httpx
import pytest

from niles.http_retry import retry_http


@retry_http
async def _dummy_request(responses: list):
    """Test helper: pops responses, raises exceptions or returns values."""
    item = responses.pop(0)
    if isinstance(item, Exception):
        raise item
    return item


@pytest.mark.asyncio
async def test_retry_on_connect_error():
    """Retries on httpx.ConnectError and succeeds on second attempt."""
    responses = [httpx.ConnectError("refused"), "ok"]
    result = await _dummy_request(responses)
    assert result == "ok"
    assert responses == []  # both items consumed


@pytest.mark.asyncio
async def test_retry_on_500():
    """Retries on HTTP 500 status error."""
    fake_request = httpx.Request("GET", "http://test")
    fake_response = httpx.Response(500, request=fake_request)
    responses = [
        httpx.HTTPStatusError("Server Error", request=fake_request, response=fake_response),
        "ok",
    ]
    result = await _dummy_request(responses)
    assert result == "ok"


@pytest.mark.asyncio
async def test_no_retry_on_400():
    """Does NOT retry on HTTP 400 (client error)."""
    fake_request = httpx.Request("GET", "http://test")
    fake_response = httpx.Response(400, request=fake_request)
    err = httpx.HTTPStatusError("Bad Request", request=fake_request, response=fake_response)
    responses = [err, "should not reach"]
    with pytest.raises(httpx.HTTPStatusError, match="Bad Request"):
        await _dummy_request(responses)
    assert len(responses) == 1  # second item not consumed


@pytest.mark.asyncio
async def test_no_retry_on_401():
    """Does NOT retry on HTTP 401 (auth error)."""
    fake_request = httpx.Request("GET", "http://test")
    fake_response = httpx.Response(401, request=fake_request)
    err = httpx.HTTPStatusError("Unauthorized", request=fake_request, response=fake_response)
    responses = [err]
    with pytest.raises(httpx.HTTPStatusError, match="Unauthorized"):
        await _dummy_request(responses)


@pytest.mark.asyncio
async def test_max_attempts():
    """Stops retrying after 3 attempts and re-raises."""
    responses = [
        httpx.ConnectError("fail 1"),
        httpx.ConnectError("fail 2"),
        httpx.ConnectError("fail 3"),
    ]
    with pytest.raises(httpx.ConnectError, match="fail 3"):
        await _dummy_request(responses)
    assert responses == []  # all 3 consumed


@pytest.mark.asyncio
async def test_success_after_transient_failure():
    """Succeeds after two transient failures."""
    fake_request = httpx.Request("GET", "http://test")
    fake_503 = httpx.Response(503, request=fake_request)
    responses = [
        httpx.ReadTimeout("timeout"),
        httpx.HTTPStatusError("Unavailable", request=fake_request, response=fake_503),
        {"data": "weather"},
    ]
    result = await _dummy_request(responses)
    assert result == {"data": "weather"}
    assert responses == []


@pytest.mark.asyncio
async def test_non_http_exception_not_retried():
    """Non-HTTP exceptions (e.g. ValueError) are NOT retried."""
    responses = [ValueError("bad data"), "should not reach"]
    with pytest.raises(ValueError, match="bad data"):
        await _dummy_request(responses)
    assert len(responses) == 1
