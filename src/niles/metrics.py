# SPDX-License-Identifier: AGPL-3.0-only
"""Prometheus metrics for Niles AI."""

from prometheus_client import Counter, Gauge, Histogram

# HTTP metrics
HTTP_REQUESTS = Counter(
    "niles_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)
HTTP_DURATION = Histogram(
    "niles_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint"],
)

# LLM metrics
LLM_DURATION = Histogram(
    "niles_llm_request_duration_seconds",
    "LLM API request duration",
)
LLM_TOKENS = Counter(
    "niles_llm_tokens_total",
    "LLM tokens consumed",
    ["type"],
)

# Tool call metrics
TOOL_CALLS = Counter(
    "niles_tool_calls_total",
    "Tool call invocations",
    ["tool_name", "success"],
)

# SSE connections
ACTIVE_SSE = Gauge(
    "niles_active_sse_connections",
    "Currently active SSE streaming connections",
)

# DB pool saturation (updated on /metrics scrape)
DB_POOL_SIZE = Gauge(
    "niles_db_pool_size",
    "Current DB connection pool size",
)
DB_POOL_FREE = Gauge(
    "niles_db_pool_free",
    "Free (idle) DB pool connections",
)
