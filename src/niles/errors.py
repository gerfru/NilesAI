"""Unified JSON error response helper per CLAUDE.md spec."""

from typing import Any

from fastapi.responses import JSONResponse


def error_response(
    status_code: int,
    message: str,
    details: Any = None,
) -> JSONResponse:
    """Return ``{"error": {"code", "message", "details"}}``."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": status_code,
                "message": message,
                "details": details,
            }
        },
    )
