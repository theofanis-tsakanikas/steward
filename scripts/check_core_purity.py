#!/usr/bin/env python3
"""Gate: the core imports nothing outside the standard library, pydantic and yaml.

The seven claims are provable on a laptop only because every decision lives in pure functions.
The day `src/steward/core/` imports `google.cloud`, `requests`, `streamlit` or an adapter, that
stops being true — so the build stops.

    python scripts/check_core_purity.py      # exit 1 on any forbidden import, with CORE_IMPURE
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORE = REPO / "src" / "steward" / "core"
ALLOWED_THIRD_PARTY = {"pydantic", "yaml"}
# The core reads no clock: "now" is always data (a capture timestamp, a ledger's as_of, an anchor date).
# A test that controlled the clock the code reads would be the code agreeing with itself (claim 6 trap).
CLOCK_MODULES = {"time"}
CLOCK_ATTRS = {"now", "today", "utcnow", "fromtimestamp", "utcfromtimestamp", "time_ns", "monotonic", "perf_counter"}
ALLOWED_INTERNAL = "steward.core"


def violations(core: Path = CORE) -> list[str]:
    found: list[str] = []
    for path in sorted(core.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import: stays inside core by construction
                    continue
                names = [node.module or ""]
            for name in names:
                if name.split(".")[0] in CLOCK_MODULES:
                    found.append(f"CORE_CLOCK {path.relative_to(REPO)}:{node.lineno} imports {name}")
                    continue
                top = name.split(".")[0]
                if name.startswith(ALLOWED_INTERNAL) or top in sys.stdlib_module_names or top in ALLOWED_THIRD_PARTY:
                    continue
                found.append(f"CORE_IMPURE {path.relative_to(REPO)}:{node.lineno} imports {name}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in CLOCK_ATTRS:
                found.append(f"CORE_CLOCK {path.relative_to(REPO)}:{node.lineno} references .{node.attr}")
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "datetime"
                and any(a.name in CLOCK_ATTRS for a in node.names)
            ):
                found.append(f"CORE_CLOCK {path.relative_to(REPO)}:{node.lineno} imports a clock from datetime")
    return found


def main() -> int:
    found = violations()
    for line in found:
        print(line)
    if found:
        print(f"FAIL core purity: {len(found)} forbidden import(s)")
        return 1
    print("ok core purity: src/steward/core imports only stdlib, pydantic, yaml, and reads no clock")
    return 0


if __name__ == "__main__":
    sys.exit(main())
