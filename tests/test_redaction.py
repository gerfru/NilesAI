"""Tests for PII / credential redaction helpers."""

from niles.redaction import redact_credentials, redact_phone, redact_tool_args


class TestRedactPhone:
    def test_keeps_last_two_digits(self):
        assert redact_phone("+43 660 1234567") == "***67"

    def test_none(self):
        assert redact_phone(None) == "***"

    def test_empty(self):
        assert redact_phone("") == "***"

    def test_too_short(self):
        assert redact_phone("12") == "***"

    def test_strips_non_digits(self):
        assert redact_phone("4366012@s.whatsapp.net") == "***12"


class TestRedactCredentials:
    def test_masks_userinfo_in_url(self):
        assert (
            redact_credentials("https://user:pass@host/path")  # pragma: allowlist secret
            == "https://***@host/path"
        )

    def test_leaves_plain_text(self):
        assert redact_credentials("connection refused") == "connection refused"

    def test_leaves_url_without_credentials(self):
        assert redact_credentials("https://host/path") == "https://host/path"


class TestRedactToolArgs:
    def test_masks_sensitive_values(self):
        out = redact_tool_args({"to": "+4366012345", "limit": 5})
        assert out["to"] == "<redacted len=11>"
        assert out["limit"] == 5

    def test_case_insensitive_keys(self):
        out = redact_tool_args({"Text": "hello there"})
        assert out["Text"] == "<redacted len=11>"

    def test_non_dict(self):
        assert redact_tool_args("just a string") == "<non-dict args>"

    def test_keeps_non_sensitive(self):
        out = redact_tool_args({"days": 7, "source": "caldav"})
        assert out == {"days": 7, "source": "caldav"}
