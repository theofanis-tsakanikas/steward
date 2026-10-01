"""Claim 2 (compiled side) — same query, different answer, by role.

Two readings, kept as independent as a single author can make them:
  expected — from the contracts and _roles.yaml, by the rules written in docs/DECISIONS.md B12–B13,
             with its own seat derivation and its own literal masking map (nothing imported from the
             compiler but the quarantine suffix and the access gate it scores)
  compiled — from the generated Terraform only (core/simulate.py never sees a contract, and refuses
             any IAM it does not model)
Checked:
  A. every policy tag: the exact set of (seat → clear | rule) the compiled IAM grants, independent of
     dataset access — so a Fine-Grained Reader handed to a seat that cannot read the dataset today
     (the custodian) is still caught
  B. every seat × column, standing and with approved marketplace grants (the grants are this eval's
     scenario, not something compiled: claim 6 issues them)
  C. every seat × table row filter
  D. every column of a table no contract declares is denied to every seat, even with a grant
  E. the access gate (role ceilings, masking/type fit) on the committed contracts
Not claimed offline: that BigQuery enforces any of it (T012 captures live role transcripts; B8).
"""

from __future__ import annotations

import sys

from steward import io, pipeline
from steward.core.compile import QUARANTINE_SUFFIX, check
from steward.core.findings import Finding, report
from steward.core.simulate import DENIED_COLUMN, DENIED_DATASET, answer, effective, model, row_filter, tag_grant

# The eval's own reading of the contract vocabulary → BigQuery predefined expressions.
MASK = {"hash": "SHA256", "nullify": "ALWAYS_NULL", "last_four": "LAST_FOUR_CHARACTERS", "email_mask": "EMAIL_MASK", "year_only": "DATE_YEAR_MASK", "default": "DEFAULT_MASKING_VALUE", "clear": "clear"}  # fmt: skip

# The quarantine table's own metadata columns (DECISIONS B14), written here, not imported: untagged,
# and only on <table>__quarantine.
QUARANTINE_METADATA = {"_run_id", "_rule_ids", "_row_key", "_routed_to", "_failures", "_quarantined_at"}

QUERY_TABLE = "crm.customers"
QUERY_COLUMNS = ["customer_id", "msisdn", "email", "birth_date", "country", "segment"]


def seats_of(e, role: str, c) -> list[str]:
    """The eval's own reading of _roles.yaml (B13) — deliberately not the compiler's seats_for()."""
    r = e.roles.roles[role]
    if r.bound_from:
        return [getattr(c, r.bound_from)]
    return [f"{role}@{x}" for x in r.scopes] if r.scopes else [role]


def _contract(e, ds):
    return next((c for c in e.contracts if c.dataset == ds), None)


def _roles_of(e, c, seat: str) -> set[str]:
    """Which roles this seat plays on contract c (B13: steward/custodian are the contract's own principals)."""
    out = set()
    for role, r in e.roles.roles.items():
        if r.bound_from:
            if getattr(c, r.bound_from) == seat:
                out.add(role)
        elif seat == role or seat.startswith(role + "@"):
            out.add(role)
    return out


def expected(e, seat: str, fqn: str, granted) -> str:
    ds, table, path = fqn.split(".", 2)
    is_quarantine = table.endswith(QUARANTINE_SUFFIX)
    table = table.removesuffix(QUARANTINE_SUFFIX)  # a quarantine table carries its source's payload and tags
    c = _contract(e, ds)
    if c is None:
        return DENIED_DATASET
    roles = _roles_of(e, c, seat)
    standing = roles & (set(c.readers) | {"custodian"})  # B12: the custodian writes, so it can read
    via_grant = {r for r in roles if r in c.marketplace.grantable_roles and (seat, ds) in granted}
    if not standing and not via_grant:
        return DENIED_DATASET
    cols = c.tables[table].columns
    if path not in cols:
        if is_quarantine and path in QUARANTINE_METADATA:
            return "clear"
        return DENIED_COLUMN  # a column the contract does not declare compiles `restricted` (B13 rule 4)
    col = cols[path]
    if not col.classification.tagged:
        return "clear"
    rules = {MASK[col.masking[r].value] for r in roles if r in col.masking}
    if not rules:
        return DENIED_COLUMN
    return "clear" if "clear" in rules else sorted(rules)[0]


def expected_filter(e, seat: str, table: str) -> str | None:
    ds, tname = table.split(".")
    tname = tname.removesuffix(QUARANTINE_SUFFIX)
    c = _contract(e, ds)
    if c is None or c.tables[tname].row_access.column is None:
        return "TRUE"
    col = c.tables[tname].row_access.column
    roles = _roles_of(e, c, seat) & (set(c.readers) | set(c.marketplace.grantable_roles) | {"custodian"})
    if not roles:
        return None
    for role in roles:
        r = e.roles.roles[role]
        if r.scoped_by != col:
            return "TRUE"
    return f'{col} = "{seat.split("@")[1]}"'


def expected_tag_grants(e, am) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for c in e.contracts:
        for fqn, _, _, col in c.iter_columns():
            if not col.classification.tagged:
                continue
            tag = am.column_tag[fqn]
            for role, m in col.masking.items():
                for seat in seats_of(e, role, c):
                    out.setdefault(tag, {})[seat] = MASK[m.value]
    return out


def evaluate() -> dict:
    e = pipeline.load()
    am = model(e.compiled["infra/estate/generated.tf.json"], e.compiled["infra/governance/generated.tf.json"])
    seats = sorted({s for c in e.contracts for r in e.roles.roles for s in seats_of(e, r, c)})
    columns = sorted(am.column_tag)
    contracted = {c.dataset for c in e.contracts}
    mismatches = []

    # A — per tag, independent of dataset access
    exp_tags = expected_tag_grants(e, am)
    tags = sorted(set(exp_tags) | set(am.fine_grained) | set(am.masked))
    for tag in tags:
        got = {s: tag_grant(am, s, tag) for s in seats if tag_grant(am, s, tag)}
        if got != exp_tags.get(tag, {}):
            mismatches.append(
                {
                    "scenario": "tag grants",
                    "seat": "*",
                    "column": tag,
                    "expected": exp_tags.get(tag, {}),
                    "compiled": got,
                }
            )

    # B — seat × column
    grants = frozenset(
        (s, c.dataset) for c in e.contracts for r in c.marketplace.grantable_roles for s in seats_of(e, r, c)
    )
    checked = 0
    for scenario, granted in (("standing", frozenset()), ("with approved grants", grants)):
        for seat in seats:
            for col in columns:
                if col.split(".")[0] not in contracted:
                    continue
                exp, got = expected(e, seat, col, granted), effective(am, seat, col, granted)
                checked += 1
                if exp != got:
                    mismatches.append(
                        {"scenario": scenario, "seat": seat, "column": col, "expected": exp, "compiled": got}
                    )
    # C — row filters
    filters = 0
    for table in sorted({".".join(c.split(".")[:2]) for c in columns if c.split(".")[0] in contracted}):
        for seat in seats:
            exp, got = expected_filter(e, seat, table), row_filter(am, seat, table)
            filters += 1
            if exp != got:
                mismatches.append(
                    {"scenario": "row filter", "seat": seat, "column": table, "expected": exp, "compiled": got}
                )
    # D — uncontracted
    uncontracted = [c for c in columns if c.split(".")[0] not in contracted]
    leaks = [
        (s, c)
        for c in uncontracted
        for s in seats
        for g in (frozenset(), frozenset({(s, c.split(".")[0])}))
        if not effective(am, s, c, g).startswith("denied")
    ]

    rows = io.synthetic_rows(QUERY_TABLE)
    types = {f["name"]: f["type"] for f in io.harvest()[QUERY_TABLE]["fields"]}
    crm = _contract(e, "crm")
    query_seats = ["analyst@GR", "fraud_investigator", crm.steward]
    answers = [
        answer(
            am, s, QUERY_TABLE, QUERY_COLUMNS, rows, types, granted=grants if s == "fraud_investigator" else frozenset()
        )
        for s in query_seats
    ]
    return {
        "checked_tags": len(tags),
        "checked_column_decisions": checked,
        "checked_row_filters": filters,
        "mismatches": mismatches,
        "uncontracted_columns": len(uncontracted),
        "uncontracted_leaks": leaks,
        "gate_findings": [f.to_dict() for f in check(e.contracts, e.roles)],
        "query": {
            "sql": f"SELECT {', '.join(QUERY_COLUMNS)} FROM {QUERY_TABLE} ORDER BY customer_id LIMIT 5",
            "mode": "SIMULATED from compiled Terraform",
            "note": "fraud_investigator reads crm through an approved marketplace grant (claim 6); the steward seat is crm's steward group",
            "answers": answers,
        },
    }


def main() -> int:
    from steward.core.simulate import Unmodelled

    try:
        r = evaluate()
    except Unmodelled as exc:
        print(f"UNMODELLED_ACCESS {exc}")
        print("FAIL claim 2 (compiled side): the compiled Terraform grants access the model cannot evaluate")
        return 1
    print(
        f"compiled vs contract: {r['checked_tags']} policy tags, {r['checked_column_decisions']} seat×column decisions, {r['checked_row_filters']} seat×table row filters"
    )
    for m in r["mismatches"][:20]:
        print(f"  MISMATCH {m}")
    print(
        f"tables with no contract: {r['uncontracted_columns']} columns, denied to every seat: {'yes' if not r['uncontracted_leaks'] else 'NO ' + str(r['uncontracted_leaks'][:3])}"
    )
    code, lines = report("access", [Finding(**f) for f in r["gate_findings"]])
    print("\n".join("  " + ln for ln in lines))
    print(f"same query, three seats ({r['query']['mode']}): {r['query']['sql']}")
    for a in r["query"]["answers"]:
        if "error" in a:
            print(f"  {a['seat']:38} {a['error']}")
        else:
            first = a["rows"][0] if a["rows"] else {}
            print(
                f"  {a['seat']:38} rows {a['rows_visible']}/{a['rows_total']}  msisdn={first.get('msisdn')!s:.16}  email={first.get('email')}  birth_date={first.get('birth_date')}"
            )
    if r["mismatches"] or r["uncontracted_leaks"] or code:
        print("FAIL claim 2 (compiled side)")
        return 1
    print("ok claim 2 (compiled side): the compiled controls are exactly what the contracts imply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
