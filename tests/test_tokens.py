"""Tests for the token budgeting helpers (tiktoken approximation)."""

from niles.tokens import count_tokens, fit_history, truncate_to_tokens


class TestCountTokens:
    def test_empty_is_zero(self):
        assert count_tokens("") == 0

    def test_nonempty_positive(self):
        assert count_tokens("hallo welt") > 0


class TestTruncate:
    def test_within_budget_unchanged(self):
        assert truncate_to_tokens("kurz", 100) == "kurz"

    def test_over_budget_shrinks(self):
        out = truncate_to_tokens("wort " * 100, 10)
        assert count_tokens(out) <= 10

    def test_zero_budget_empty(self):
        assert truncate_to_tokens("etwas", 0) == ""


class TestFitHistory:
    def test_all_fit(self):
        hist = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        assert fit_history(hist, 1000) == hist

    def test_zero_budget_empty(self):
        assert fit_history([{"role": "user", "content": "a"}], 0) == []

    def test_keeps_newest_drops_oldest(self):
        hist = [
            {"role": "user", "content": "alt " * 50},
            {"role": "user", "content": "neu"},
        ]
        kept = fit_history(hist, count_tokens("neu") + 10)
        assert kept == [{"role": "user", "content": "neu"}]
