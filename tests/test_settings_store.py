"""Tests for runtime settings store and apply_overrides."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from niles.config import Settings, apply_overrides
from niles.crypto import FieldEncryptor
from niles.settings_store import (
    EDITABLE_SETTINGS,
    SettingsStore,
    _ENCRYPTED_KEYS,
    _validate_key,
)


class TestEditableWhitelist:
    def test_contains_expected_keys(self):
        expected = {
            "llm_base_url",
            "llm_model",
            "timezone",
            "log_level",
            "feature_whatsapp_send_others",
            "caldav_calendars",
            "feature_signal_send_others",
            "signal_api_url",
            "signal_phone_number",
            "signal_disabled",
            "feature_briefing_daily",
            "feature_briefing_weekly",
            "briefing_daily_time",
            "briefing_weekly_time",
            "briefing_channel",
            "weather_latitude",
            "weather_longitude",
            "weather_location_name",
            "feature_search",
            "searxng_url",
            "notion_token",
            "notion_sync_interval",
            "notion_embedding_model",
            "notion_chunk_size",
            "notion_chunk_overlap",
            "notion_similarity_threshold",
            "feature_notion",
        }
        assert EDITABLE_SETTINGS == expected

    def test_does_not_contain_credentials(self):
        """Infrastructure credentials that must never be runtime-editable."""
        forbidden = {
            "postgres_password",
            "evolution_api_key",
            "niles_api_key",
            "caldav_password",
        }
        assert forbidden.isdisjoint(EDITABLE_SETTINGS)


class TestKeyValidation:
    def test_valid_keys_pass(self):
        for key in ["llm_model", "feature_tool_send_whatsapp", "log_level"]:
            _validate_key(key)  # Should not raise

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError, match="Invalid settings key"):
            _validate_key("LLM_MODEL")

    def test_rejects_special_chars(self):
        with pytest.raises(ValueError, match="Invalid settings key"):
            _validate_key("key; DROP TABLE")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="Invalid settings key"):
            _validate_key("a" * 65)

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="Invalid settings key"):
            _validate_key("")

    def test_rejects_starts_with_number(self):
        with pytest.raises(ValueError, match="Invalid settings key"):
            _validate_key("1_bad_key")


class TestApplyOverrides:
    def test_returns_new_instance(self):
        settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
        )
        result = apply_overrides(settings, {"llm_model": "new-model"})
        assert result is not settings
        assert result.llm_model == "new-model"
        # Original unchanged
        assert settings.llm_model != "new-model"

    def test_applies_string_override(self):
        settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
        )
        result = apply_overrides(settings, {"llm_model": "new-model"})
        assert result.llm_model == "new-model"

    def test_applies_bool_override(self):
        settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
        )
        assert settings.feature_whatsapp_send_others is True
        result = apply_overrides(settings, {"feature_whatsapp_send_others": False})
        assert result.feature_whatsapp_send_others is False

    def test_ignores_unknown_keys(self):
        settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
        )
        result = apply_overrides(settings, {"nonexistent_key": "value"})
        assert result is settings  # No change, returns same instance
        assert not hasattr(result, "nonexistent_key")

    def test_applies_multiple_overrides(self):
        settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
        )
        result = apply_overrides(
            settings,
            {
                "timezone": "US/Eastern",
                "log_level": "DEBUG",
            },
        )
        assert result.timezone == "US/Eastern"
        assert result.log_level == "DEBUG"


class TestSettingsStoreEncryption:
    """Test that SettingsStore encrypts/decrypts sensitive keys."""

    @pytest.fixture
    def enc(self):
        return FieldEncryptor(FieldEncryptor.generate_key())

    @pytest.fixture
    def conn(self):
        """Mock connection with transaction context manager."""
        conn = AsyncMock()
        # conn.transaction() is a sync call returning an async context manager
        tx_ctx = MagicMock()
        tx_ctx.__aenter__ = AsyncMock()
        tx_ctx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx_ctx)
        return conn

    @pytest.fixture
    def store(self, enc, conn):
        pool = AsyncMock()
        # asyncpg pool.acquire() is a sync call returning an async context manager
        acq_ctx = MagicMock()
        acq_ctx.__aenter__ = AsyncMock(return_value=conn)
        acq_ctx.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=acq_ctx)
        return SettingsStore(pool, encryptor=enc)

    def test_encrypted_keys_are_editable(self):
        """All keys in _ENCRYPTED_KEYS must be in EDITABLE_SETTINGS."""
        assert _ENCRYPTED_KEYS.issubset(EDITABLE_SETTINGS)

    async def test_set_encrypts_sensitive_key(self, store, enc, conn):
        await store.set("notion_token", "ntn_secret_abc123")
        args = conn.execute.call_args[0]
        stored_json = args[2]
        stored_value = json.loads(stored_json)
        assert stored_value.startswith("v1:")
        assert enc.decrypt(stored_value) == "ntn_secret_abc123"

    async def test_set_does_not_encrypt_nonsensitive_key(self, store, conn):
        await store.set("llm_model", "gpt-4o")
        args = conn.execute.call_args[0]
        stored_json = args[2]
        assert json.loads(stored_json) == "gpt-4o"

    async def test_get_all_decrypts_sensitive_keys(self, store, enc):
        encrypted_token = enc.encrypt("ntn_secret_abc123")
        store.pool.fetch.return_value = [
            {"key": "notion_token", "value": json.dumps(encrypted_token)},
            {"key": "llm_model", "value": json.dumps("gpt-4o")},
        ]
        result = await store.get_all()
        assert result["notion_token"] == "ntn_secret_abc123"
        assert result["llm_model"] == "gpt-4o"

    async def test_get_all_handles_legacy_plaintext(self, store):
        """Pre-encryption plaintext values are returned as-is."""
        store.pool.fetch.return_value = [
            {"key": "notion_token", "value": json.dumps("plain-legacy-token")},
        ]
        result = await store.get_all()
        assert result["notion_token"] == "plain-legacy-token"


class TestURLValidation:
    """Test URL scheme validation for searxng_url and llm_base_url."""

    @pytest.fixture
    def store(self):
        pool = AsyncMock()
        conn = AsyncMock()
        acq_ctx = MagicMock()
        acq_ctx.__aenter__ = AsyncMock(return_value=conn)
        acq_ctx.__aexit__ = AsyncMock(return_value=False)
        pool.acquire = MagicMock(return_value=acq_ctx)
        tx_ctx = MagicMock()
        tx_ctx.__aenter__ = AsyncMock()
        tx_ctx.__aexit__ = AsyncMock(return_value=False)
        conn.transaction = MagicMock(return_value=tx_ctx)
        return SettingsStore(pool)

    async def test_llm_base_url_rejects_file_scheme(self, store):
        with pytest.raises(ValueError, match="must be http:// or https://"):
            await store.set("llm_base_url", "file:///etc/passwd")

    async def test_llm_base_url_rejects_no_hostname(self, store):
        with pytest.raises(ValueError, match="must be http:// or https://"):
            await store.set("llm_base_url", "http://")

    async def test_llm_base_url_accepts_private_host(self, store):
        """Private hosts are allowed (LLM typically on Docker internal network)."""
        await store.set("llm_base_url", "http://host.docker.internal:11434/v1")

    async def test_llm_base_url_accepts_https(self, store):
        await store.set("llm_base_url", "https://api.openai.com/v1")

    async def test_searxng_url_rejects_invalid_scheme(self, store):
        with pytest.raises(ValueError, match="must be http:// or https://"):
            await store.set("searxng_url", "ftp://searxng:8080")
