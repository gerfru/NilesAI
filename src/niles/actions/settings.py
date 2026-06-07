"""Runtime settings validation, coercion, and persistence."""

import httpx

from ..config import Settings, apply_overrides
from ..settings_store import SettingsStore


class SettingsAction:
    """Validate, coerce, and persist runtime settings."""

    def __init__(self, settings_store: SettingsStore, *, http_client: httpx.AsyncClient):
        self.settings_store = settings_store
        self.http_client = http_client

    async def update(self, key: str, value: str, current_settings: Settings) -> Settings:
        """Validate key, coerce type, persist, return new Settings.

        Raises ValueError for unknown keys or persistence failures.
        """
        if not hasattr(current_settings, key):
            raise ValueError(f"Unbekannte Einstellung: '{key}'")
        parsed: str | bool
        if key.startswith("feature_"):
            parsed = value.lower() in ("true", "1", "on")
        else:
            parsed = value
        await self.settings_store.set(key, parsed)
        return apply_overrides(current_settings, {key: parsed})

    async def list_ollama_models(self, base_url: str, current_model: str) -> list[dict]:
        """Fetch available models from Ollama.

        Returns list of {name, selected} dicts.
        Raises on connection failure.
        """
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        resp = await self.http_client.get(f"{base}/api/tags", timeout=5)
        resp.raise_for_status()
        models = sorted((m["name"] for m in resp.json().get("models", [])), key=str.lower)
        return [{"name": m, "selected": m == current_model} for m in models]
