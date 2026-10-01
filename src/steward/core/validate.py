"""Contract validation: each contract alone (doctrine 3), the contracts together, and the contracts
against the harvested estate (drift). Waivers applied last, with an explicit `today`.
"""

from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from .contract import Contract, Roles, Waiver, parse_contract
from .findings import UNWAIVABLE, Finding
from .schema import harvest_columns

GATE = "contracts"

# A missing required field gets a code that names what is missing (so a gate-proof marker can tell
# "retention missing" apart from "contract broken somehow").
_MISSING_CODES = {
    "retention": "RETENTION_MISSING",
    "owner": "OWNERSHIP_MISSING",
    "steward": "OWNERSHIP_MISSING",
    "custodian": "OWNERSHIP_MISSING",
    "classification": "CLASSIFICATION_MISSING",
    "legal_basis": "RETENTION_MISSING",
    "period_days": "RETENTION_MISSING",
}


def load_contract(name: str, doc: dict) -> tuple[Contract | None, list[Finding]]:
    try:
        return parse_contract(doc), []
    except ValidationError as e:
        out = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            leaf = str(err["loc"][-1]) if err["loc"] else ""
            code = _MISSING_CODES.get(leaf, "CONTRACT_INVALID") if err["type"] == "missing" else "CONTRACT_INVALID"
            if code == "CONTRACT_INVALID" and err["type"] == "missing" and leaf == "retention":
                code = "RETENTION_MISSING"
            out.append(Finding(code, GATE, f"{name}:{loc}", err["msg"]))
        return None, out


def cross_check(contracts: list[Contract], roles: Roles) -> list[Finding]:
    f: list[Finding] = []
    known_roles = set(roles.roles)
    known_principals = set(roles.directory)
    all_columns = {fqn: col for c in contracts for fqn, _, _, col in c.iter_columns()}
    seen_rule_ids: dict[str, str] = {}

    datasets = [c.dataset for c in contracts]
    for d in {d for d in datasets if datasets.count(d) > 1}:
        f.append(Finding("DATASET_DUPLICATE", GATE, d, "two contracts claim the same dataset"))

    for c in contracts:
        for who in ("owner", "steward", "custodian"):
            p = getattr(c, who)
            if p not in known_principals:
                f.append(Finding("PRINCIPAL_UNKNOWN", GATE, f"{c.dataset}.{who}", f"{p} is not in the directory"))
        if c.marketplace.approvers not in known_principals:
            f.append(
                Finding("PRINCIPAL_UNKNOWN", GATE, f"{c.dataset}.marketplace", f"{c.marketplace.approvers} unknown")
            )
        for r in c.marketplace.grantable_roles:
            if r not in known_roles:
                f.append(Finding("ROLE_UNKNOWN", GATE, f"{c.dataset}.marketplace", f"role {r!r} is not defined"))

        for tname, t in c.tables.items():
            tfq = f"{c.dataset}.{tname}"
            cols = t.columns
            for k in t.primary_key:
                if k not in cols:
                    f.append(Finding("COLUMN_REFERENCE_UNKNOWN", GATE, tfq, f"primary key {k!r} is not a column"))
            refs = [("retention", t.retention.column)]
            if t.row_access:
                refs.append(("row_access", t.row_access.column))
            if t.freshness:
                refs.append(("freshness", t.freshness.column))
            for what, col in refs:
                if col not in cols:
                    f.append(Finding("COLUMN_REFERENCE_UNKNOWN", GATE, tfq, f"{what} column {col!r} is not a column"))
            if t.retention.period_days and t.retention.period_days > c.retention.period_days:
                f.append(
                    Finding(
                        "RETENTION_EXCEEDS_DATASET",
                        GATE,
                        tfq,
                        f"table keeps {t.retention.period_days}d > dataset {c.retention.period_days}d",
                    )
                )
            if (
                t.retention.mode == "partition"
                and t.retention.column in cols
                and cols[t.retention.column].type not in ("DATE", "TIMESTAMP")
            ):
                f.append(
                    Finding("RETENTION_COLUMN_TYPE", GATE, tfq, "partition retention needs a DATE/TIMESTAMP column")
                )
            rule_ids = [t.freshness.id] if t.freshness else []
            for path, col in cols.items():
                if "." in path and path.rsplit(".", 1)[0] not in cols:
                    f.append(
                        Finding(
                            "COLUMN_PARENT_UNDECLARED", GATE, f"{tfq}.{path}", "nested leaf without its parent RECORD"
                        )
                    )
                for role in col.masking:
                    if role not in known_roles:
                        f.append(
                            Finding("ROLE_UNKNOWN", GATE, f"{tfq}.{path}", f"masking names undefined role {role!r}")
                        )
                for rule in col.quality:
                    rule_ids.append(rule.id)
                    if rule.kind == "referential" and rule.references not in all_columns:
                        f.append(
                            Finding(
                                "REFERENCE_DANGLING",
                                GATE,
                                f"{tfq}.{path}",
                                f"{rule.id} references {rule.references}, which no contract declares",
                            )
                        )
            for rid in rule_ids:
                if rid in seen_rule_ids:
                    f.append(Finding("RULE_ID_DUPLICATE", GATE, rid, f"used by {seen_rule_ids[rid]} and {tfq}"))
                seen_rule_ids[rid] = tfq
    return f


def against_estate(contracts: list[Contract], harvest: dict) -> list[Finding]:
    """Drift: what the estate has that the contracts do not say, and the reverse."""
    f: list[Finding] = []
    estate = harvest_columns(harvest)
    declared = {f"{c.dataset}.{t}": (c, tbl) for c in contracts for t, tbl in c.tables.items()}
    contracted_datasets = {c.dataset for c in contracts}

    for table, cols in sorted(estate.items()):
        dataset = table.split(".")[0]
        if table not in declared:
            code = "TABLE_UNDECLARED" if dataset in contracted_datasets else "CONTRACT_MISSING"
            f.append(
                Finding(
                    code,
                    GATE,
                    table,
                    "exists in the estate; no contract declares it — every column treated as sensitive and denied",
                )
            )
            continue
        _, tbl = declared[table]
        for path, info in sorted(cols.items()):
            col = tbl.columns.get(path)
            if col is None:
                f.append(
                    Finding(
                        "COLUMN_UNDECLARED",
                        GATE,
                        f"{table}.{path}",
                        f"{info.type} column exists in the estate but not in the contract",
                    )
                )
            elif col.type != info.type:
                f.append(
                    Finding(
                        "TYPE_MISMATCH", GATE, f"{table}.{path}", f"contract says {col.type}, estate has {info.type}"
                    )
                )
        for path in sorted(set(tbl.columns) - set(cols)):
            f.append(
                Finding(
                    "COLUMN_ABSENT",
                    GATE,
                    f"{table}.{path}",
                    "declared in the contract but absent from the estate — the catalog would describe a column that does not exist",
                )
            )
    for table in sorted(set(declared) - set(estate)):
        f.append(Finding("TABLE_ABSENT", GATE, table, "declared in the contract but absent from the estate"))
    return f


def apply_waivers(findings: list[Finding], waivers: list[Waiver], roles: Roles, today: date) -> list[Finding]:
    """Suppress a finding only with a live waiver approved by a human. Doctrine 6 and 7."""
    out: list[Finding] = []
    used: set[str] = set()
    for w in waivers:
        if w.finding in UNWAIVABLE:
            out.append(
                Finding(
                    "WAIVER_REFUSED",
                    GATE,
                    w.id,
                    f"{w.finding} cannot be waived by anyone (doctrine 7): the values are the evidence; remove the data instead",
                )
            )
        if not w.approved_by.startswith("user:"):
            out.append(
                Finding(
                    "WAIVER_REFUSED",
                    GATE,
                    w.id,
                    f"approved by {w.approved_by}: only a named human may approve an exception (doctrine 5)",
                )
            )
    valid = {
        (w.finding, w.target): w for w in waivers if w.finding not in UNWAIVABLE and w.approved_by.startswith("user:")
    }
    for fd in findings:
        w = valid.get((fd.code, fd.target))
        if w is None:
            out.append(fd)
            continue
        used.add(w.id)
        if date.fromisoformat(w.expires) < today:
            out.append(fd)
            out.append(
                Finding(
                    "WAIVER_EXPIRED",
                    GATE,
                    w.id,
                    f"expired {w.expires}; {fd.code} on {fd.target} is back",
                    severity="warn",
                )
            )
        else:
            out.append(
                Finding(fd.code, fd.gate, fd.target, fd.message, fd.severity, waived_by=f"{w.id} until {w.expires}")
            )
    for w in waivers:
        if w.id not in used and w.finding not in UNWAIVABLE:
            out.append(Finding("WAIVER_UNUSED", GATE, w.id, "matches no finding — remove it", severity="warn"))
    return out


def validate_all(
    contract_docs: dict[str, dict], roles_doc: dict, waivers_doc: dict, harvest: dict, today: date
) -> tuple[list[Contract], list[Finding]]:
    findings: list[Finding] = []
    contracts: list[Contract] = []
    for name, doc in sorted(contract_docs.items()):
        c, errs = load_contract(name, doc)
        findings += errs
        if c:
            contracts.append(c)
    roles = Roles.model_validate(roles_doc)
    waivers = [Waiver.model_validate(w) for w in waivers_doc.get("waivers", [])]
    findings += cross_check(contracts, roles)
    findings += against_estate(contracts, harvest)
    return contracts, apply_waivers(findings, waivers, roles, today)
