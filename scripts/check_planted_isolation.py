#!/usr/bin/env python3
"""Gate: the planted ground truth is read by evals only.

If a detector, compiler, gate or the demo could read `synthetic/_planted.json`, claim 1 would be one
function agreeing with itself. This fails the build when the file's name appears in any source file
outside evals/ and the generator that writes it.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ALLOWED = {"synthetic/generate.py", "scripts/check_planted_isolation.py", "tests/test_synthetic.py"}
SCAN = ("src", "app", "scripts", "synthetic", "lookml", "tests")
NEEDLE = "_planted"


def violations() -> list[str]:
    out = []
    for top in SCAN:
        for p in sorted((REPO / top).rglob("*.py")) if (REPO / top).exists() else []:
            rel = str(p.relative_to(REPO))
            if rel in ALLOWED:
                continue
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if NEEDLE in line:
                    out.append(f"PLANTED_READ_OUTSIDE_EVALS {rel}:{i}")
    return out


def main() -> int:
    v = violations()
    print("\n".join(v) if v else "ok planted isolation: only evals/ read synthetic/_planted.json")
    return 1 if v else 0


if __name__ == "__main__":
    sys.exit(main())
