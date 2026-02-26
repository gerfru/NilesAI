"""Tests for structured logging configuration."""

import json
import logging

from niles.logging_config import generate_request_id, setup_logging


def test_setup_logging_produces_json(capsys):
    """setup_logging produces JSON-formatted output to stdout."""
    setup_logging("INFO")
    logging.getLogger("test.json").info("hello world")
    captured = capsys.readouterr()
    line = json.loads(captured.out.strip())
    assert line["event"] == "hello world"
    assert line["level"] == "info"
    assert "timestamp" in line


def test_generate_request_id_format():
    """Request IDs are 12-character hex strings."""
    rid = generate_request_id()
    assert len(rid) == 12
    assert rid.isalnum()


def test_generate_request_id_unique():
    """Each call produces a different ID."""
    ids = {generate_request_id() for _ in range(100)}
    assert len(ids) == 100


def test_log_level_configurable(capsys):
    """Log level configuration is respected."""
    setup_logging("WARNING")
    logging.getLogger("test.level").info("should not appear")
    logging.getLogger("test.level").warning("should appear")
    captured = capsys.readouterr()
    assert "should not appear" not in captured.out
    assert "should appear" in captured.out
