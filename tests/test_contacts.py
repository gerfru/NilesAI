"""Tests for contact lookup and phone normalization."""

from niles.actions.contacts import normalize_phone


class TestNormalizePhone:
    def test_plus_country_code(self):
        assert normalize_phone("+43 660 123 4567") == "4366012345678"

    def test_leading_zero(self):
        assert normalize_phone("0660 123 4567") == "4366012345678"

    def test_double_zero_prefix(self):
        assert normalize_phone("004366012345678") == "4366012345678"

    def test_already_normalized(self):
        assert normalize_phone("4366012345678") == "4366012345678"

    def test_with_dashes(self):
        assert normalize_phone("+43-660-123-4567") == "4366012345678"

    def test_with_parentheses(self):
        assert normalize_phone("+43 (660) 5875573") == "4366012345678"

    def test_with_dots(self):
        assert normalize_phone("+43.660.123.4567") == "4366012345678"

    def test_german_number(self):
        assert normalize_phone("+49 170 1234567") == "491701234567"

    def test_short_local(self):
        assert normalize_phone("06601234") == "436601234"
