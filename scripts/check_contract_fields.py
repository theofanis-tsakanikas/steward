#!/usr/bin/env python3
"""Gate: every field a contract can declare is read — by a named file, for a stated reason.

CLAUDE.md, the contract layer: "A field in a contract that no generator reads is a defect." Matching
field names anywhere in the code passes on collisions (`mode`, `id`, `type` are read for other objects),
so the reader of each field is declared here, explicitly, and checked: the named file must contain an
attribute access `.field`. A field missing from READERS is FIELD_UNREAD — adding a field means naming its
reader. Documentation-only fields and fields whose reader is a later atom are listed apart, with why.

    python scripts/check_contract_fields.py     # FIELD_UNREAD / READER_STALE on failure
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from pydantic import BaseModel  # noqa: E402

from steward.core import contract as C  # noqa: E402

CORE = "src/steward/core/"
READERS: dict[tuple[str, str], str] = {
    ("QualityRule", "id"): CORE + "quality.py",
    ("QualityRule", "kind"): CORE + "quality.py",
    ("QualityRule", "allowed"): CORE + "quality.py",
    ("QualityRule", "regex"): CORE + "quality.py",
    ("QualityRule", "min"): CORE + "quality.py",
    ("QualityRule", "max"): CORE + "quality.py",
    ("QualityRule", "references"): CORE + "quality.py",
    ("Freshness", "id"): CORE + "quality.py",
    ("Freshness", "column"): CORE + "quality.py",
    ("Freshness", "max_age_days"): CORE + "quality.py",
    ("Column", "type"): CORE + "retention.py",
    ("Column", "classification"): CORE + "gate_classification.py",
    ("Column", "kinds"): CORE + "gate_classification.py",
    ("Column", "masking"): CORE + "compile.py",
    ("Column", "quality"): CORE + "quality.py",
    ("TableRetention", "mode"): CORE + "retention.py",
    ("TableRetention", "column"): CORE + "retention.py",
    ("TableRetention", "period_days"): CORE + "validate.py",
    ("TableRetention", "rule"): CORE + "retention.py",
    ("RowAccess", "column"): CORE + "compile.py",
    ("Table", "description"): CORE + "compile.py",
    ("Table", "primary_key"): CORE + "quality.py",
    ("Table", "retention"): CORE + "retention.py",
    ("Table", "row_access"): CORE + "compile.py",
    ("Table", "freshness"): CORE + "quality.py",
    ("Table", "columns"): CORE + "compile.py",
    ("Retention", "period_days"): CORE + "retention.py",
    ("Retention", "legal_basis"): CORE + "retention.py",
    ("Marketplace", "listable"): CORE + "marketplace.py",
    ("Marketplace", "approvers"): CORE + "marketplace.py",
    ("Marketplace", "max_grant_days"): CORE + "marketplace.py",
    ("Marketplace", "grantable_roles"): CORE + "marketplace.py",
    ("LogSink", "personal_kinds"): CORE + "gate_classification.py",
    ("Change", "version"): CORE + "contract.py",  # the changelog validator: versions 1..n, last == version
    ("Contract", "dataset"): CORE + "compile.py",
    ("Contract", "version"): CORE + "compile.py",
    ("Contract", "description"): CORE + "compile.py",
    ("Contract", "owner"): CORE + "validate.py",
    ("Contract", "steward"): CORE + "compile.py",
    ("Contract", "custodian"): CORE + "compile.py",
    ("Contract", "lawful_basis"): CORE + "compile.py",
    ("Contract", "retention"): CORE + "retention.py",
    ("Contract", "readers"): CORE + "compile.py",
    ("Contract", "marketplace"): CORE + "marketplace.py",
    ("Contract", "changelog"): CORE + "contract.py",  # the changelog validator (doctrine 4)
    ("Contract", "log_sink"): CORE + "gate_classification.py",
    ("Contract", "tables"): CORE + "compile.py",
    ("Role", "scoped_by"): CORE + "compile.py",
    ("Role", "scopes"): CORE + "compile.py",
    ("Role", "bound_from"): CORE + "compile.py",
    ("Ceiling", "clear_kinds"): CORE + "compile.py",
    ("Roles", "roles"): CORE + "compile.py",
    ("Roles", "ceilings"): CORE + "compile.py",
    ("Roles", "seat_groups"): CORE + "marketplace.py",
    ("Roles", "waiver_approvers"): CORE + "validate.py",
    ("Roles", "directory"): CORE + "validate.py",
    ("Waiver", "id"): CORE + "validate.py",
    ("Waiver", "finding"): CORE + "validate.py",
    ("Waiver", "target"): CORE + "validate.py",
    ("Waiver", "requested_by"): CORE + "validate.py",
    ("Waiver", "approved_by"): CORE + "validate.py",
    ("Waiver", "approved_on"): CORE + "validate.py",
    ("Waiver", "expires"): CORE + "validate.py",
}
# Read by people (and shown by the catalog / demo), never by a control — stated so it is a decision.
DOCUMENTATION = {
    ("Change", "change"): "the human sentence of a changelog line",
    ("Change", "date"): "when a version was made; shown, not enforced",
    ("Role", "description"): "what a role is for",
    ("Waiver", "reason"): "why an exception exists; read by its approver",
    ("RowAccess", "none"): "the written reason all rows are visible; the absence of `column` is what compiles",
    ("LogSink", "source"): "which logs feed the sink; the sink filter itself is compiled from code",
}
# Read by an atom not yet built. Each must move to READERS when that atom lands.
PENDING = {
    ("Column", "description"): "T021 — the catalog payload's column Description attribute",
}


def models() -> list[type[BaseModel]]:
    return [
        v
        for v in vars(C).values()
        if isinstance(v, type) and issubclass(v, BaseModel) and v.__module__ == C.__name__ and v is not C.Strict
    ]


def _attrs(path: Path) -> set[str]:
    return {n.attr for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Attribute)}


def violations() -> list[str]:
    out = []
    cache: dict[str, set[str]] = {}
    for m in models():
        for f in m.model_fields:
            key = (m.__name__, f)
            if key in DOCUMENTATION or key in PENDING:
                continue
            reader = READERS.get(key)
            if reader is None:
                out.append(
                    f"FIELD_UNREAD {m.__name__}.{f} — no reader declared; name the file that reads it in scripts/check_contract_fields.py READERS"
                )
                continue
            attrs = cache.setdefault(reader, _attrs(REPO / reader))
            if f not in attrs:
                out.append(f"READER_STALE {m.__name__}.{f} — {reader} no longer reads .{f}")
    declared = {(m.__name__, f) for m in models() for f in m.model_fields}
    for key in sorted((set(READERS) | set(DOCUMENTATION) | set(PENDING)) - declared):
        out.append(f"READER_ORPHAN {key[0]}.{key[1]} — listed here but no longer a field")
    return out


def main() -> int:
    v = violations()
    n = sum(len(m.model_fields) for m in models())
    print(
        "\n".join(v)
        if v
        else f"ok contract fields: {n} fields — {len(READERS)} read by a named file, {len(DOCUMENTATION)} documentation, {len(PENDING)} pending (T021)"
    )
    return 1 if v else 0


if __name__ == "__main__":
    sys.exit(main())
