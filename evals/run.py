#!/usr/bin/env python3
"""Run every claim harness: evals/<claim>/eval.py, each exposing main() -> int."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv: list[str]) -> int:
    only = set(argv)
    harnesses = sorted(p for p in HERE.glob("*/eval.py") if not only or p.parent.name in only)
    if not harnesses:
        print("no claim harnesses yet")
        return 0
    failed: list[str] = []
    for path in harnesses:
        spec = importlib.util.spec_from_file_location(f"eval_{path.parent.name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        print(f"── {path.parent.name} " + "─" * (60 - len(path.parent.name)))
        code = mod.main()
        if code:
            failed.append(path.parent.name)
    print("─" * 64)
    if failed:
        print(f"FAIL evals: {', '.join(failed)}")
        return 1
    print(f"ok evals: {len(harnesses)} harness(es) green")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
