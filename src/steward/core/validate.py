"""Contract validation: each contract alone (doctrine 3), the contracts together, the contracts against
the harvested estate (drift), and waivers last, against an explicit `today`.
"""

from __future__ import annotations

from datetime import date

from pydantic import ValidationError

from .contract import Contract, Roles, Waiver, parse_contract
from .findings import Finding
from .schema import harvest_columns

GATE = "contracts"

# Doctrine 3 and 6 together: only "this table has no contract yet" may be waived — the legacy case,
# where every column is held at the safe state until an owner is found. Everything else a waiver
# could switch off (a missing owner, retention, classification, an undeclared column) is a default
# being invented with a deadline attached, so it is not waivable at all.
WAIVABLE = frozenset({"CONTRACT_MISSING", "TABLE_UNDECLARED"})

_MISSING_CODES = {
    "retention": "RETENTION_MISSING",
    "legal_basis": "RETENTION_MISSING",
    "period_days": "RETENTION_MISSING",
    "owner": "OWNERSHIP_MISSING",
    "steward": "OWNERSHIP_MISSING",
    "custodian": "OWNERSHIP_MISSING",
    "classification": "CLASSIFICATION_MISSING",
    "row_access": "ROW_ACCESS_MISSING",
}


def _absent(err: dict) -> bool:
    """`missing` or an explicit null — both mean the declaration is not there."""
    return err["type"] == "missing" or err.get("input", ...) is None


def load_contract(name: str, doc: dict) -> tuple[Contract | None, list[Finding]]:
    try:
        return parse_contract(doc), []
    except ValidationError as e:
        out = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            leaf = str(err["loc"][-1]) if err["loc"] else ""
            code = _MISSING_CODES.get(leaf, "CONTRACT_INVALID") if _absent(err) else "CONTRACT_INVALID"
            out.append(Finding(code, GATE, f"{name}:{loc}" if loc else name, err["msg"]))
        return None, out


def _resolves_to_humans(roles: Roles, principal: str) -> tuple[bool, str]:
    members = roles.members(principal) if principal.startswith("group:") else [principal]
    if not members:
        return False, "has no members"
    if any(m.startswith("serviceAccount:") for m in members):
        return False, "includes a service account"
    if not any(m.startswith("user:") for m in members):
        return False, "has no named human"
    return True, ""


def cross_check(contracts: list[Contract], roles: Roles) -> list[Finding]:
    f: list[Finding] = []
    known_roles = set(roles.roles)
    known_principals = set(roles.directory)
    all_columns = {fqn: col for c in contracts for fqn, _, _, col in c.iter_columns()}
    seen_rule_ids: dict[str, str] = {}
    scoped_columns = {r.scoped_by for r in roles.roles.values() if r.scoped_by}

    datasets = [c.dataset for c in contracts]
    for d in sorted({d for d in datasets if datasets.count(d) > 1}):
        f.append(Finding("DATASET_DUPLICATE", GATE, d, "two contracts claim the same dataset"))

    for c in contracts:
        for who in ("owner", "steward", "custodian"):
            p = getattr(c, who)
            if p not in known_principals:
                f.append(Finding("PRINCIPAL_UNKNOWN", GATE, f"{c.dataset}.{who}", f"{p} is not in the directory"))
        # Separation of duties (doctrine 5): the people who own and approve are people, and not the
        # pipeline that writes the data.
        for who, p in (("owner", c.owner), ("steward", c.steward), ("marketplace.approvers", c.marketplace.approvers)):
            ok, why = _resolves_to_humans(roles, p)
            if not ok and p in known_principals:
                f.append(
                    Finding(
                        "DUTY_NOT_HUMAN",
                        GATE,
                        f"{c.dataset}.{who}",
                        f"{p} {why}; ownership and approval belong to named humans",
                    )
                )
        if c.owner == c.custodian:
            f.append(Finding("DUTY_CONFLICT", GATE, f"{c.dataset}.owner", "owner and custodian are the same principal"))
        if c.marketplace.approvers == c.custodian:
            f.append(
                Finding(
                    "DUTY_CONFLICT",
                    GATE,
                    f"{c.dataset}.marketplace.approvers",
                    "the custodian may not approve access to what it writes",
                )
            )
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
            if t.row_access.column:
                refs.append(("row_access", t.row_access.column))
            if t.freshness:
                refs.append(("freshness", t.freshness.column))
            for what, col in refs:
                if col not in cols:
                    f.append(Finding("COLUMN_REFERENCE_UNKNOWN", GATE, tfq, f"{what} column {col!r} is not a column"))
            if (
                t.freshness
                and t.freshness.column in cols
                and cols[t.freshness.column].type not in ("DATE", "TIMESTAMP")
            ):
                f.append(Finding("COLUMN_TYPE_INVALID", GATE, tfq, "freshness needs a DATE/TIMESTAMP column"))
            if t.retention.column in cols and cols[t.retention.column].type not in ("DATE", "TIMESTAMP"):
                f.append(Finding("COLUMN_TYPE_INVALID", GATE, tfq, "retention needs a DATE/TIMESTAMP column"))
            ra = t.row_access.column
            if ra in cols:
                if cols[ra].classification.tagged:
                    f.append(
                        Finding(
                            "ROW_ACCESS_ON_TAGGED",
                            GATE,
                            tfq,
                            f"row access on {ra!r}, a tagged column: the filter would leak what the tag hides",
                        )
                    )
                if ra not in scoped_columns:
                    f.append(
                        Finding(
                            "ROW_ACCESS_UNSCOPED",
                            GATE,
                            tfq,
                            f"row access on {ra!r}, but no role is scoped by it (scoped_by: {sorted(scoped_columns)})",
                        )
                    )
            if t.retention.period_days and t.retention.period_days > c.retention.period_days:
                f.append(
                    Finding(
                        "RETENTION_EXCEEDS_DATASET",
                        GATE,
                        tfq,
                        f"table keeps {t.retention.period_days}d > dataset {c.retention.period_days}d",
                    )
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


def against_estate(contracts: list[Contract], harvest: dict, broken: frozenset[str] = frozenset()) -> list[Finding]:
    """Drift: what the estate has that the contracts do not say, and the reverse. Tables of a
    dataset whose contract failed to load are skipped: that contract is already a blocking finding,
    and reporting its tables as CONTRACT_MISSING would make them look waivable."""
    f: list[Finding] = []
    estate = harvest_columns(harvest)
    declared = {f"{c.dataset}.{t}": (c, tbl) for c in contracts for t, tbl in c.tables.items()}
    contracted_datasets = {c.dataset for c in contracts}

    for table, cols in sorted(estate.items()):
        dataset = table.split(".")[0]
        if dataset in broken:
            continue
        if table not in declared:
            code = "TABLE_UNDECLARED" if dataset in contracted_datasets else "CONTRACT_MISSING"
            f.append(
                Finding(
                    code,
                    GATE,
                    table,
                    "exists in the estate; no contract declares it — the compiled controls must deny every column to every role (doctrine 1)",
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
        partition = harvest[table].get("partition")
        if tbl.retention.mode == "partition" and tbl.retention.column != partition:
            f.append(
                Finding(
                    "RETENTION_PARTITION_MISMATCH",
                    GATE,
                    table,
                    f"partition retention on {tbl.retention.column!r}, but the estate partitions on {partition!r}",
                )
            )
        if tbl.retention.mode == "row" and partition and tbl.retention.column == partition:
            f.append(
                Finding(
                    "RETENTION_MODE_WRONG",
                    GATE,
                    table,
                    "row retention on the partition column — declare `mode: partition`",
                    severity="warn",
                )
            )
    for table in sorted(set(declared) - set(estate)):
        f.append(Finding("TABLE_ABSENT", GATE, table, "declared in the contract but absent from the estate"))
    return f


def load_waivers(doc: dict) -> tuple[list[Waiver], list[Finding]]:
    out, errs = [], []
    for i, raw in enumerate(doc.get("waivers", []) or []):
        try:
            out.append(Waiver.model_validate(raw))
        except ValidationError as e:
            wid = raw.get("id", f"#{i}") if isinstance(raw, dict) else f"#{i}"
            for err in e.errors():
                errs.append(
                    Finding("WAIVER_INVALID", GATE, str(wid), f"{'.'.join(map(str, err['loc']))}: {err['msg']}")
                )
    return out, errs


def apply_waivers(
    findings: list[Finding], waivers: list[Waiver], roles: Roles, contracts: list[Contract], today: date
) -> list[Finding]:
    """Suppress a finding only with a live, properly approved waiver. Doctrines 5, 6, 7."""
    out: list[Finding] = []
    owners = {c.dataset: c.owner for c in contracts}
    valid: dict[tuple[str, str], Waiver] = {}
    for w in waivers:
        refusals = []
        if w.finding not in WAIVABLE:
            refusals.append(
                f"{w.finding} is not waivable (only {', '.join(sorted(WAIVABLE))}); fix the declaration instead"
            )
        if not w.approved_by.startswith("user:"):
            refusals.append(f"approved by {w.approved_by}: only a named human may approve an exception (doctrine 5)")
        elif not roles.is_member(w.approved_by, roles.waiver_approvers):
            refusals.append(f"{w.approved_by} is not a member of {roles.waiver_approvers}")
        if w.approved_by == w.requested_by:
            refusals.append("requester approved their own waiver (doctrine 5)")
        owner = owners.get(w.target.split(".")[0])
        if owner and roles.is_member(w.approved_by, owner):
            refusals.append(
                f"{w.approved_by} owns {w.target.split('.')[0]}: an owner may not waive their own dataset's findings"
            )
        if w.approved_on > today:
            refusals.append(f"approved_on {w.approved_on} is in the future")
        if (w.finding, w.target) in valid:
            refusals.append(f"duplicate of {valid[(w.finding, w.target)].id} for the same finding and target")
        for r in refusals:
            out.append(Finding("WAIVER_REFUSED", GATE, w.id, r))
        if not refusals:
            valid[(w.finding, w.target)] = w
    used: set[str] = set()
    for fd in findings:
        w = valid.get((fd.code, fd.target))
        if w is None:
            out.append(fd)
            continue
        used.add(w.id)
        if w.expires < today:
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
    for w in valid.values():
        if w.id not in used:
            out.append(
                Finding(
                    "WAIVER_UNUSED", GATE, w.id, "matches no finding — a stale exception re-matches later; remove it"
                )
            )
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
    waivers, werrs = load_waivers(waivers_doc)
    findings += werrs
    findings += cross_check(contracts, roles)
    loaded = {c.dataset for c in contracts}
    broken = frozenset(str(d.get("dataset", n)) for n, d in contract_docs.items() if isinstance(d, dict)) - loaded
    findings += against_estate(contracts, harvest, broken)
    return contracts, apply_waivers(findings, waivers, roles, contracts, today)
