#!/usr/bin/env python3
"""Gate: every field a contract can declare is read — by a named file, for a stated reason.

CLAUDE.md, the contract layer: "A field in a contract that no generator reads is a defect." Matching
field names anywhere in the code passes on collisions (`mode`, `id`, `type` are read for other objects),
so the reader of each field is declared here, explicitly, and checked: the named file must contain the
attribute access `<receiver>.field` with one of the receivers named (`col.type`, not `info.type`). A field missing from READERS is FIELD_UNREAD — adding a field means naming its
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
READERS: dict[tuple[str, str], tuple[str, list[str]]] = {
    ("QualityRule", "id"): (CORE + "quality.py", ["rule"]),
    ("QualityRule", "kind"): (CORE + "quality.py", ["rule"]),
    ("QualityRule", "allowed"): (CORE + "quality.py", ["rule"]),
    ("QualityRule", "regex"): (CORE + "quality.py", ["rule"]),
    ("QualityRule", "min"): (CORE + "quality.py", ["rule"]),
    ("QualityRule", "max"): (CORE + "quality.py", ["rule"]),
    ("QualityRule", "references"): (CORE + "quality.py", ["rule"]),
    ("Freshness", "id"): (CORE + "quality.py", ["fr"]),
    ("Freshness", "column"): (CORE + "quality.py", ["fr"]),
    ("Freshness", "max_age_days"): (CORE + "quality.py", ["fr"]),
    ("Column", "type"): (CORE + "validate.py", ["col"]),
    ("Column", "classification"): (CORE + "gate_classification.py", ["col"]),
    ("Column", "kinds"): (CORE + "gate_classification.py", ["col"]),
    ("Column", "masking"): (CORE + "compile.py", ["col"]),
    ("Column", "quality"): (CORE + "quality.py", ["col"]),
    ("TableRetention", "mode"): (CORE + "retention.py", ["t.retention"]),
    ("TableRetention", "column"): (CORE + "retention.py", ["t.retention"]),
    ("TableRetention", "period_days"): (CORE + "validate.py", ["t.retention"]),
    ("TableRetention", "rule"): (CORE + "retention.py", ["t.retention"]),
    ("RowAccess", "column"): (CORE + "compile.py", ["tbl.row_access"]),
    ("Table", "description"): (CORE + "compile.py", ["tbl"]),
    ("Table", "primary_key"): (CORE + "quality.py", ["tbl"]),
    ("Table", "retention"): (CORE + "retention.py", ["t"]),
    ("Table", "row_access"): (CORE + "compile.py", ["tbl"]),
    ("Table", "freshness"): (CORE + "quality.py", ["tbl"]),
    ("Table", "columns"): (CORE + "compile.py", ["tbl"]),
    ("Retention", "period_days"): (CORE + "retention.py", ["c.retention"]),
    ("Retention", "legal_basis"): (CORE + "retention.py", ["c.retention"]),
    ("Marketplace", "listable"): (CORE + "marketplace.py", ["ds.marketplace"]),
    ("Marketplace", "approvers"): (CORE + "marketplace.py", ["ds.marketplace"]),
    ("Marketplace", "max_grant_days"): (CORE + "marketplace.py", ["ds.marketplace"]),
    ("Marketplace", "grantable_roles"): (CORE + "marketplace.py", ["ds.marketplace"]),
    ("LogSink", "personal_kinds"): (CORE + "gate_classification.py", ["sinks[dataset]"]),
    ("Change", "version"): (CORE + "contract.py", ["c"]),  # the changelog validator: versions 1..n, last == version
    ("Contract", "dataset"): (CORE + "compile.py", ["c"]),
    ("Contract", "version"): (CORE + "compile.py", ["c"]),
    ("Contract", "description"): (CORE + "compile.py", ["c"]),
    ("Contract", "owner"): (CORE + "validate.py", ["c"]),
    ("Contract", "steward"): (CORE + "compile.py", ["c"]),
    ("Contract", "custodian"): (CORE + "compile.py", ["c"]),
    ("Contract", "lawful_basis"): (CORE + "compile.py", ["c"]),
    ("Contract", "retention"): (CORE + "retention.py", ["c"]),
    ("Contract", "readers"): (CORE + "compile.py", ["c"]),
    ("Contract", "marketplace"): (CORE + "marketplace.py", ["ds"]),
    ("Contract", "changelog"): (CORE + "contract.py", ["self"]),  # the changelog validator (doctrine 4)
    ("Contract", "log_sink"): (CORE + "gate_classification.py", ["c"]),
    ("Contract", "tables"): (CORE + "compile.py", ["c"]),
    ("Role", "scoped_by"): (CORE + "compile.py", ["r"]),
    ("Role", "scopes"): (CORE + "compile.py", ["r"]),
    ("Role", "bound_from"): (CORE + "compile.py", ["r"]),
    ("Ceiling", "clear_kinds"): (CORE + "compile.py", ["ceiling"]),
    ("Roles", "roles"): (CORE + "compile.py", ["roles"]),
    ("Roles", "ceilings"): (CORE + "compile.py", ["roles"]),
    ("Roles", "ceiling_changes"): (CORE + "versioning.py", ["roles"]),
    ("CeilingChange", "role"): (CORE + "versioning.py", ["ch"]),
    ("CeilingChange", "kinds_added"): (CORE + "versioning.py", ["ch"]),
    ("CeilingChange", "requested_by"): (CORE + "versioning.py", ["ch"]),
    ("CeilingChange", "approved_by"): (CORE + "versioning.py", ["ch"]),
    ("Roles", "seat_groups"): (CORE + "marketplace.py", ["roles"]),
    ("Roles", "waiver_approvers"): (CORE + "validate.py", ["roles"]),
    ("Roles", "directory"): (CORE + "validate.py", ["roles"]),
    ("Waiver", "id"): (CORE + "validate.py", ["w"]),
    ("Waiver", "finding"): (CORE + "validate.py", ["w"]),
    ("Waiver", "target"): (CORE + "validate.py", ["w"]),
    ("Waiver", "requested_by"): (CORE + "validate.py", ["w"]),
    ("Waiver", "approved_by"): (CORE + "validate.py", ["w"]),
    ("Waiver", "approved_on"): (CORE + "validate.py", ["w"]),
    ("Waiver", "expires"): (CORE + "validate.py", ["w"]),
}
# Read by people (and shown by the catalog / demo), never by a control — stated so it is a decision.
DOCUMENTATION = {
    ("Change", "change"): "the human sentence of a changelog line",
    ("Change", "date"): "when a version was made; shown, not enforced",
    ("Role", "description"): "what a role is for",
    ("Waiver", "reason"): "why an exception exists; read by its approver",
    ("CeilingChange", "reason"): "why a ceiling was raised; read by its approver",
    ("CeilingChange", "approved_on"): "when; shown in the access review",
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


def _reads(path: Path) -> set[tuple[str, str]]:
    """(receiver source, attribute) for every attribute access — `col.type` is ("col", "type")."""
    return {
        (ast.unparse(n.value), n.attr) for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Attribute)
    }


def violations() -> list[str]:
    out = []
    cache: dict[str, set[tuple[str, str]]] = {}
    for m in models():
        for f in m.model_fields:
            key = (m.__name__, f)
            if key in DOCUMENTATION or key in PENDING:
                continue
            entry = READERS.get(key)
            if entry is None:
                out.append(
                    f"FIELD_UNREAD {m.__name__}.{f} — no reader declared; name the file that reads it in scripts/check_contract_fields.py READERS"
                )
                continue
            reader, receivers = entry
            reads = cache.setdefault(reader, _reads(REPO / reader))
            if not any((r, f) in reads for r in receivers):
                out.append(
                    f"READER_STALE {m.__name__}.{f} — {reader} no longer reads {' / '.join(r + '.' + f for r in receivers)}"
                )
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
