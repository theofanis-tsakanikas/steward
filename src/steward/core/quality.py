"""Claim 5 — quality rules from contracts; a failing row is quarantined with its rule and routed to its
owner, never dropped.

`run()` takes the source rows as the loader received them and returns three things: what loads, what is
quarantined (with every failing rule id, a row key, the run id and the owner it is routed to — and the
row itself, because a quarantined row that does not keep its payload has been dropped with extra
steps), and table-level findings such as freshness.

The count that proves nothing was lost is NOT computed here. A reconciliation computed from this
function's own output reconciles trivially; the gate (gate_quality.py) takes the source count from the
source, counted before the rules ran, by a different reader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .contract import Contract, QualityRule
from .findings import Finding

GATE = "quality"


@dataclass
class QuarantineRecord:
    run_id: str
    table: str
    offset: int  # position in the source as received
    row_key: str  # primary key values @ offset — unique even for duplicate keys
    rule_ids: list[str]
    failures: list[dict]  # [{rule_id, kind, column, reason}]
    routed_to: str  # the dataset owner (contract)
    steward: str
    row: dict

    def to_dict(self, with_row: bool = False) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "row"}
        if with_row:
            d["row"] = self.row
        return d


@dataclass
class RunResult:
    run_id: str
    table: str
    rows_in: int  # what this function was handed — reported, never used as the reconciliation source
    loaded: list[dict] = field(default_factory=list)
    quarantined: list[QuarantineRecord] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def leaf_values(row: dict, path: str) -> list:
    """All values at a dotted path, descending through records and repeated records."""
    cur: list = [row]
    for part in path.split("."):
        nxt: list = []
        for obj in cur:
            if isinstance(obj, dict):
                v = obj.get(part)
                nxt.extend(v if isinstance(v, list) else [v])
        cur = nxt
    return cur


def _num(v) -> Decimal | None:
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _check(rule: QualityRule, values: list, refs: dict[str, set], seen: dict[str, set]) -> str | None:
    """Return a reason if the row fails this rule, else None."""
    present = [v for v in values if v is not None and v != ""]
    if rule.kind == "completeness":
        return "missing value" if len(present) < max(1, len(values)) else None
    if rule.kind == "validity":
        for v in present:
            if rule.allowed is not None and str(v) not in rule.allowed:
                return f"{v!r} not in {rule.allowed}"
            if rule.regex is not None and not re.fullmatch(rule.regex, str(v)):
                return f"{v!r} does not match {rule.regex}"
            if rule.min is not None or rule.max is not None:
                n = _num(v)
                if n is None:
                    return f"{v!r} is not a number"
                if rule.min is not None and n < Decimal(str(rule.min)):
                    return f"{v} < {rule.min}"
                if rule.max is not None and n > Decimal(str(rule.max)):
                    return f"{v} > {rule.max}"
        return None
    if rule.kind == "uniqueness":
        bucket = seen.setdefault(rule.id, set())
        for v in present:
            if v in bucket:
                return f"{v!r} already loaded earlier in this run"
        return None
    if rule.kind == "referential":
        ref = refs.get(rule.references or "")
        if ref is None:
            return f"reference {rule.references} not available — cannot prove the row valid"
        for v in present:
            if v not in ref:
                return f"{v!r} not found in {rule.references}"
        return None
    raise ValueError(rule.kind)


def run(contract: Contract, table: str, rows: list[dict], refs: dict[str, set], run_id: str, today: date) -> RunResult:
    """Apply every rule the contract declares for `table` to every row, in source order.

    Uniqueness keeps the first occurrence and quarantines later ones. A row failing several rules is
    quarantined once, carrying all of them. Nothing is dropped: every input row is either loaded or
    quarantined, and the function asserts it before returning.
    """
    tbl = contract.tables[table]
    fqn = f"{contract.dataset}.{table}"
    rules = [(path, r) for path, col in tbl.columns.items() for r in col.quality]
    res = RunResult(run_id, fqn, rows_in=len(rows))
    seen: dict[str, set] = {}
    for offset, row in enumerate(rows):
        failures = []
        for path, rule in rules:
            reason = _check(rule, leaf_values(row, path), refs, seen)
            if reason:
                failures.append({"rule_id": rule.id, "kind": rule.kind, "column": path, "reason": reason})
        if failures:
            key = "|".join(str(row.get(k)) for k in tbl.primary_key)
            res.quarantined.append(
                QuarantineRecord(
                    run_id,
                    fqn,
                    offset,
                    f"{key}@{offset}",
                    sorted({f["rule_id"] for f in failures}),
                    failures,
                    contract.owner,
                    contract.steward,
                    row,
                )
            )
            continue
        # only a loaded row claims its unique values; a quarantined duplicate must not block a later valid row
        for path, rule in rules:
            if rule.kind == "uniqueness":
                seen.setdefault(rule.id, set()).update(v for v in leaf_values(row, path) if v not in (None, ""))
        res.loaded.append(row)

    if tbl.freshness:
        fr = tbl.freshness
        vals = [v for r in rows for v in leaf_values(r, fr.column) if v]
        newest = max((date.fromisoformat(str(v)[:10]) for v in vals), default=None)
        if newest is None or (today - newest).days > fr.max_age_days:
            res.findings.append(
                Finding(
                    "FRESHNESS_STALE",
                    GATE,
                    fqn,
                    f"{fr.id}: newest {fr.column} is {newest} — older than {fr.max_age_days} days on {today}; routed to {contract.owner}",
                    evidence={"rule_id": fr.id, "routed_to": contract.owner},
                )
            )
    if len(res.loaded) + len(res.quarantined) != len(rows):
        raise AssertionError(f"{fqn}: {len(rows)} in, {len(res.loaded)} loaded + {len(res.quarantined)} quarantined")
    return res


def new_run_id(table: str, when: datetime) -> str:
    return f"run-{when.strftime('%Y%m%dT%H%M%SZ')}-{table.replace('.', '-')}"
