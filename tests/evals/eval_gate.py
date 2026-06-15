# SPDX-License-Identifier: AGPL-3.0-only
"""Regression gate for the golden-dataset LLM evals.

Reads a pytest-json-report file and a baseline, and fails (exit 1) when the
number of passing golden cases drops below ``baseline.pass - baseline.tolerance``.
The tolerance absorbs the non-determinism of a local model (llama3.1:8b) so a
single flaky case does not turn the nightly job red.

Run by the CI job after `pytest -m llm_eval --json-report`:
    uv run python tests/evals/eval_gate.py [report.json] [baseline.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def evaluate(report: dict, baseline: dict) -> tuple[bool, str]:
    """Return (passed_gate, message) comparing a json-report to the baseline."""
    summary = report.get("summary", {})
    passed = summary.get("passed", 0)
    total = summary.get("total", summary.get("collected", 0))
    floor = baseline["pass"] - baseline.get("tolerance", 1)
    ok = passed >= floor
    verdict = "OK" if ok else "REGRESSION"
    msg = (
        f"[{verdict}] golden evals: {passed}/{total} passed; "
        f"baseline={baseline['pass']}, tolerance={baseline.get('tolerance', 1)}, floor={floor}"
    )
    return ok, msg


def main(argv: list[str]) -> int:
    report_path = Path(argv[1]) if len(argv) > 1 else Path("eval-report.json")
    baseline_path = Path(argv[2]) if len(argv) > 2 else Path("tests/evals/baseline.json")
    report = json.loads(report_path.read_text())
    baseline = json.loads(baseline_path.read_text())
    ok, msg = evaluate(report, baseline)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
