"""Tests for runtime settings store and apply_overrides."""

import pytest

from niles.config import Settings, apply_overrides
from niles.settings_store import EDITABLE_SETTINGS, _validate_key


class TestEditableWhitelist:
    def test_contains_expected_keys(self):
        expected = {
            "llm_base_url",
            "llm_model",
            "timezone",
            "log_level",
            "feature_whatsapp_send_others",
            "caldav_calendars",
            "carddav_url",
            "carddav_user",
            "carddav_password",
            "feature_vikunja",
            "feature_signal",
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
