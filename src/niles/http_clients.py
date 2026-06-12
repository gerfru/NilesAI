# SPDX-License-Identifier: AGPL-3.0-only
"""Shared httpx.AsyncClient instances for connection pooling."""

import httpx

from .config import Settings


class HttpClients:
    """Container for shared httpx clients, one per external service group.

    All clients are long-lived and share connection pools.  Per-request
    overrides (timeout, auth, headers) can be passed to individual calls.
    """

    def __init__(self, settings: Settings):
        self.evolution = httpx.AsyncClient(
            headers={"apikey": settings.evolution_api_key},
            timeout=30,
        )
        self.open_meteo = httpx.AsyncClient(timeout=10)
        self.geocoding = httpx.AsyncClient(timeout=5)
        self.google_oauth = httpx.AsyncClient(timeout=30)
        self.general = httpx.AsyncClient(timeout=10)

    async def close_all(self) -> None:
        for client in (
            self.evolution,
            self.open_meteo,
            self.geocoding,
            self.google_oauth,
            self.general,
        ):
            await client.aclose()
