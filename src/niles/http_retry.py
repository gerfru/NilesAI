"""Retry utilities for transient httpx failures.

Usage::

    from niles.http_retry import retry_http

    @retry_http
    async def fetch_weather(client, url):
        resp = await client.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()

Only retries on transient errors (connection, timeout, 5xx).
Does NOT retry on 4xx (client errors indicate a bug or bad input).
"""

import logging

import httpx
import tenacity

logger = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient HTTP errors worth retrying."""
    if isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
        ),
    ):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def _log_retry(retry_state: tenacity.RetryCallState) -> None:
    """Log each retry attempt."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    logger.warning(
        "HTTP retry %d/3: %s",
        retry_state.attempt_number,
        str(exc)[:200] if exc else "unknown",
    )


retry_http = tenacity.retry(
    retry=tenacity.retry_if_exception(_is_retryable),
    wait=tenacity.wait_exponential_jitter(initial=1, max=10, jitter=2),
    stop=tenacity.stop_after_attempt(3),
    before_sleep=_log_retry,
    reraise=True,
)
