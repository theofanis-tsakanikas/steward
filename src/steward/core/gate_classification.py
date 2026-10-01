"""Claim 1's gate: no column in which personal data was found by value is unclassified.

Inputs are the detector's output and the contracts — the detector never saw the contracts, so this is
the first point where the two meet. Doctrine 7: this gate takes no waivers as input at all — no
exception mechanism can reach it; the only way past a finding is to remove the data or tag the column.
"""

from __future__ import annotations

from .classify import ColumnDetection
from .contract import Contract
from .findings import Finding

GATE = "classification"


def gate(detections: list[ColumnDetection], contracts: list[Contract]) -> list[Finding]:
    declared: dict[str, tuple] = {}
    tables: set[str] = set()
    for c in contracts:
        for fqn, tname, path, col in c.iter_columns():
            declared[fqn] = (c, tname, path, col)
        tables.update(f"{c.dataset}.{t}" for t in c.tables)

    out: list[Finding] = []
    for d in detections:
        if not d.kinds:
            continue
        table = ".".join(d.column.split(".")[:2])
        ev = {"hits": d.hits, "n_values": d.n_values}
        if table not in tables:
            out.append(
                Finding(
                    "PII_IN_UNCONTRACTED_TABLE",
                    GATE,
                    d.column,
                    f"{', '.join(d.kinds)} found by value in a table no contract declares; denied to every role until one does",
                    severity="warn",
                    evidence=ev,
                )
            )
            continue
        if d.column not in declared:
            out.append(
                Finding(
                    "PII_UNDECLARED_COLUMN",
                    GATE,
                    d.column,
                    f"{', '.join(d.kinds)} found by value; the contract does not declare this column",
                    evidence=ev,
                )
            )
            continue
        _, _, _, col = declared[d.column]
        if not col.classification.tagged:
            out.append(
                Finding(
                    "PII_UNTAGGED",
                    GATE,
                    d.column,
                    f"{', '.join(d.kinds)} found by value ({sum(d.hits.get(k, 0) for k in d.kinds)}/{d.n_values} values) but the contract classifies it `{col.classification}` — no policy tag, no masking",
                    evidence=ev,
                )
            )
            continue
        missing = sorted(set(d.kinds) - set(col.kinds))
        if missing:
            out.append(
                Finding(
                    "KIND_UNDECLARED",
                    GATE,
                    d.column,
                    f"found {', '.join(missing)} by value; the contract declares only {', '.join(col.kinds)} — role ceilings are judged on declared kinds, so the stricter reading wins",
                    evidence=ev,
                )
            )
    return out
