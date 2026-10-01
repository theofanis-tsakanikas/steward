#!/usr/bin/env python3
"""Gate: every field a contract can declare is read by at least one generator or gate.

CLAUDE.md, the contract layer: "A field in a contract that no generator reads is a defect." This walks the
pydantic models in src/steward/core/contract.py and requires each field to be read — as an attribute
(`.field`) or a string key — somewhere in src/steward outside contract.py itself. A field nobody reads is
a promise the system silently does not keep.

    python scripts/check_contract_fields.py     # FIELD_UNREAD <Model>.<field> on failure
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src" / "steward"
sys.path.insert(0, str(REPO / "src"))

from pydantic import BaseModel  # noqa: E402

from steward.core import contract as C  # noqa: E402

# Fields that are documentation by design — read by humans and the catalog, never by a control.
DOCUMENTATION = {
    ("Change", "change"),
    ("Change", "date"),
    ("Role", "description"),
    ("Waiver", "reason"),
    ("TableRetention", "rule"),
}


def models() -> list[type[BaseModel]]:
    return [
        v
        for v in vars(C).values()
        if isinstance(v, type) and issubclass(v, BaseModel) and v.__module__ == C.__name__ and v is not C.Strict
    ]


def reads() -> set[str]:
    names: set[str] = set()
    for p in SRC.rglob("*.py"):
        if p.name == "contract.py" and p.parent.name == "core":
            continue
        for node in ast.walk(ast.parse(p.read_text())):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
    return names


def violations() -> list[str]:
    used = reads()
    out = []
    for m in models():
        for f in m.model_fields:
            if (m.__name__, f) in DOCUMENTATION:
                continue
            if f not in used:
                out.append(f"FIELD_UNREAD {m.__name__}.{f} — declared by contracts, read by no generator or gate")
    return out


def main() -> int:
    v = violations()
    print(
        "\n".join(v)
        if v
        else f"ok contract fields: every field of {len(models())} models is read by a generator or gate"
    )
    return 1 if v else 0


if __name__ == "__main__":
    sys.exit(main())
