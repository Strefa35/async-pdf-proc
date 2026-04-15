#!/usr/bin/env python3
"""
Run the pytest integration suite with JUnit XML + HTML report (replaces tests/run_pytest.sh).

Usage (from project root):
  python3 tests/run_pytest.py
  python3 tests/run_pytest.py -k health
Environment:
  PYTEST_VENV  Path to venv (default: .pytest-venv in project root)
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests._runner_util import default_report_args, run_pytest, run_pytest_preflight


def main() -> int:
    preflight_rc = run_pytest_preflight(sys.argv[1:])
    if preflight_rc != 0:
        return preflight_rc
    extra = ["-vv", "--tb=short", *default_report_args(), *sys.argv[1:]]
    return run_pytest(extra)


if __name__ == "__main__":
    raise SystemExit(main())
