#!/usr/bin/env python3
"""Every figure the demo shows comes from an evidence file: no literal in app/ may look like one.

Refused in app/**/*.py (docstrings excepted):
  * an int literal outside -1..12 (layout counts such as st.columns(4) stay legal), or any float literal
  * a string literal holding a run of two or more digits (a date, a count, an id typed into the page)

The figures a page prints are computed from evidence — `len(rows)`, `f"{x:.0%}"` — so none needs to be typed.
Exit 1 with DEMO_FIGURE_HARDCODED <file>:<line> for each.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "app"
MAX_LAYOUT_INT = 12


def docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                out.add(id(body[0].value))
    return out


def problems(root: Path = APP) -> list[str]:
    out = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text())
        skip = docstrings(tree)
        rel = path.relative_to(root.parent)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or id(node) in skip:
                continue
            v = node.value
            bad = (
                isinstance(v, float)
                or (isinstance(v, int) and not isinstance(v, bool) and not -1 <= v <= MAX_LAYOUT_INT)
                or (isinstance(v, str) and re.search(r"\d{2,}", v))
            )
            if bad:
                out.append(
                    f"ERROR DEMO_FIGURE_HARDCODED {rel}:{node.lineno} — {v!r} looks like a figure: read it from evidence/"
                )
    return out


def main() -> int:
    found = problems()
    print("\n".join(found))
    if found:
        print(f"FAIL demo-figures: {len(found)} blocking finding(s)")
        return 1
    print("ok demo-figures: no hard-coded figure in app/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
