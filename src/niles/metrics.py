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
