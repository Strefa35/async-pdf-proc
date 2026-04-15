#!/usr/bin/env python3
"""
Run FR-tagged tests in configurable order (replaces tests/run_all_fr_tests.sh).

Examples:
  python3 tests/run_fr_tests.py
  python3 tests/run_fr_tests.py --reverse
  python3 tests/run_fr_tests.py --shuffle
  python3 tests/run_fr_tests.py --order fr7,fr5,fr1
  python3 tests/run_fr_tests.py --only fr3,fr5,multi
  python3 tests/run_fr_tests.py --only fr1 -x

Each tag runs in a separate pytest subprocess so order is preserved. The \"multi\"
tag runs with PDF_FILE removed from the environment so all fixtures under tests/fixtures/pdf/ are visible.
Trailing arguments are forwarded to pytest.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests._runner_util import default_report_args, run_pytest

DEFAULT_ORDER = ["fr1", "fr2", "fr3", "fr4", "fr5", "fr6", "fr7", "multi"]


def resolve_order(ns: argparse.Namespace) -> list[str]:
    if ns.only:
        return [t.strip() for t in ns.only.split(",") if t.strip()]
    if ns.order:
        return [t.strip() for t in ns.order.split(",") if t.strip()]
    if ns.reverse:
        return ["fr7", "fr6", "fr5", "fr4", "fr3", "fr2", "fr1", "multi"]
    order = list(DEFAULT_ORDER)
    if ns.shuffle:
        random.shuffle(order)
    return order


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reverse", action="store_true", help="Run fr7..fr1 then multi")
    parser.add_argument("--shuffle", action="store_true", help="Randomize tag order (includes multi)")
    parser.add_argument("--order", type=str, metavar="TAGS", help="Comma-separated tags, e.g. fr7,fr5,multi")
    parser.add_argument("--only", type=str, metavar="TAGS", help="Run only these comma-separated tags")
    ns, pytest_tail = parser.parse_known_args(argv)
    pytest_tail = [a for a in pytest_tail if a != "--"]
    order = resolve_order(ns)
    base_extra = ["-vv", "--tb=short", *default_report_args()]

    known = set(DEFAULT_ORDER)
    for tag in order:
        if tag not in known:
            print(f"[skip] unknown tag: {tag!r}", file=sys.stderr)
            continue
        print(f"\n>>> pytest -m {tag}")
        env = os.environ.copy()
        if tag == "multi":
            env.pop("PDF_FILE", None)
        rc = run_pytest([*base_extra, "-m", tag, *pytest_tail], env=env)
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
