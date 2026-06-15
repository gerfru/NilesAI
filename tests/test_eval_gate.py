"""Tests for the golden-dataset eval regression gate (tests/evals/eval_gate.py)."""

from tests.evals.eval_gate import evaluate

_BASELINE = {"pass": 19, "total": 20, "tolerance": 1}


def _report(passed: int, total: int = 20) -> dict:
    return {"summary": {"passed": passed, "total": total}}


def test_pass_above_baseline_ok():
    ok, msg = evaluate(_report(20), _BASELINE)
    assert ok
    assert "OK" in msg


def test_one_regression_within_tolerance_ok():
    ok, _ = evaluate(_report(18), _BASELINE)  # floor = 19 - 1 = 18
    assert ok


def test_below_floor_fails():
    ok, msg = evaluate(_report(17), _BASELINE)
    assert not ok
    assert "REGRESSION" in msg


def test_zero_tolerance():
    ok, _ = evaluate(_report(18), {"pass": 19, "total": 20, "tolerance": 0})
    assert not ok
