"""Tests for NotionSummarizer (sync/notion_summarizer.py)."""

from unittest.mock import AsyncMock, MagicMock

import httpx

from niles.sync.notion_summarizer import NotionSummarizer


# ---------- Helpers ----------------------------------------------------------


def _summarizer(max_input_chars=4000, max_tokens=200):
    return NotionSummarizer(
        ollama_base_url="http://localhost:11434",
        model="llama3.1:8b",
        max_input_chars=max_input_chars,
        max_tokens=max_tokens,
    )


# ---------- summarize --------------------------------------------------------


class TestSummarize:
    async def test_success(self):
        s = _summarizer()
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"response": "This is a summary."}
        fake_resp.raise_for_status = MagicMock()
        s._client = AsyncMock()
        s._client.post.return_value = fake_resp

        result = await s.summarize("Some content", title="Test Page")

        assert result == "This is a summary."
        call_args = s._client.post.call_args
        assert "/api/generate" in call_args[0][0]
        body = call_args[1]["json"]
        assert body["model"] == "llama3.1:8b"
        assert "Test Page" in body["prompt"]
        assert "Some content" in body["prompt"]
        assert body["stream"] is False
        assert body["options"]["num_predict"] == 200

    async def test_http_error_returns_none(self):
        s = _summarizer()
        s._client = AsyncMock()
        s._client.post.side_effect = httpx.ConnectError("refused")

        result = await s.summarize("content", title="Page")

        assert result is None

    async def test_empty_response_returns_none(self):
        s = _summarizer()
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"response": ""}
        fake_resp.raise_for_status = MagicMock()
        s._client = AsyncMock()
        s._client.post.return_value = fake_resp

        result = await s.summarize("content")

        assert result is None

    async def test_whitespace_response_returns_none(self):
        s = _summarizer()
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"response": "   \n  "}
        fake_resp.raise_for_status = MagicMock()
        s._client = AsyncMock()
        s._client.post.return_value = fake_resp

        result = await s.summarize("content")

        assert result is None

    async def test_truncation_for_long_content(self):
        s = _summarizer(max_input_chars=100)
        fake_resp = MagicMock()
        fake_resp.json.return_value = {"response": "Summary."}
        fake_resp.raise_for_status = MagicMock()
        s._client = AsyncMock()
        s._client.post.return_value = fake_resp

        long_content = "A" * 200
        await s.summarize(long_content, title="Long")

        body = s._client.post.call_args[1]["json"]
        # Content should be truncated with [...] marker
        assert "[...]" in body["prompt"]
        # First half (50 chars) + [...] + last half (50 chars)
        assert "A" * 50 in body["prompt"]


# ---------- URL handling -----------------------------------------------------


class TestURLHandling:
    def test_url_strips_v1_suffix(self):
        s = NotionSummarizer(
            ollama_base_url="http://localhost:11434/v1",
            model="test",
        )
        assert s._ollama_url == "http://localhost:11434"

    def test_url_strips_trailing_slash(self):
        s = NotionSummarizer(
            ollama_base_url="http://localhost:11434/",
            model="test",
        )
        assert s._ollama_url == "http://localhost:11434"


# ---------- close ------------------------------------------------------------


class TestClose:
    async def test_close(self):
        s = _summarizer()
        s._client = AsyncMock()
        await s.close()
        s._client.aclose.assert_called_once()


# ---------- model property ---------------------------------------------------


class TestModel:
    def test_model_property(self):
        s = _summarizer()
        assert s.model == "llama3.1:8b"
