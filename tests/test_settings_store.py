"""Tests for runtime settings store and apply_overrides."""

from niles.config import Settings, apply_overrides
from niles.settings_store import EDITABLE_SETTINGS


class TestEditableWhitelist:
    def test_contains_expected_keys(self):
        expected = {
            "llm_base_url", "llm_model", "timezone", "log_level",
            "feature_whatsapp_auto_reply", "feature_tool_send_whatsapp",
            "feature_carddav_sync", "feature_caldav_sync",
        }
        assert EDITABLE_SETTINGS == expected

    def test_does_not_contain_credentials(self):
        forbidden = {
            "postgres_password", "evolution_api_key", "niles_api_key",
            "carddav_password", "caldav_password",
        }
        assert forbidden.isdisjoint(EDITABLE_SETTINGS)


class TestApplyOverrides:
    def test_applies_string_override(self):
        settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
        )
        apply_overrides(settings, {"llm_model": "new-model"})
        assert settings.llm_model == "new-model"

    def test_applies_bool_override(self):
        settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
        )
        assert settings.feature_whatsapp_auto_reply is False
        apply_overrides(settings, {"feature_whatsapp_auto_reply": True})
        assert settings.feature_whatsapp_auto_reply is True

    def test_ignores_unknown_keys(self):
        settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
        )
        apply_overrides(settings, {"nonexistent_key": "value"})
        assert not hasattr(settings, "nonexistent_key")

    def test_applies_multiple_overrides(self):
        settings = Settings(
            _env_file=None,
            postgres_password="test",
            evolution_api_key="test",
        )
        apply_overrides(settings, {
            "timezone": "US/Eastern",
            "log_level": "DEBUG",
        })
        assert settings.timezone == "US/Eastern"
        assert settings.log_level == "DEBUG"
