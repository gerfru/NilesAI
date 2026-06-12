# SPDX-License-Identifier: AGPL-3.0-only
"""Unified JSON error response helper per CLAUDE.md spec."""

import re
from typing import Any

from fastapi.responses import JSONResponse

_URL_PATTERN = re.compile(r"https?://[^\s,)]+")


def sanitize_error(exc: Exception) -> str:
    """Return a safe error string with internal URLs stripped."""
    msg = str(exc)
    return _URL_PATTERN.sub("<internal-service>", msg)


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
