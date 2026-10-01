"""Claim 2 (compiled side) — same query, different answer, by role.

Two independent readings:
  expected  — from the contracts: readers / marketplace grants / per-role masking / row_access
  compiled  — from the generated Terraform only (core/simulate.py never sees a contract)
Every seat × every column × {standing, with an approved grant} must agree, every row filter must agree,
every column of a table with no contract must be denied to every seat, and the access gate (role
ceilings, masking/type fit) must be green.

Not claimed offline: that BigQuery enforces any of it. T012 captures three live role transcripts.
"""

from __future__ import annotations

import sys

from steward import io, pipeline
from steward.core.compile import PREDEFINED, check
from steward.core.findings import report
from steward.core.simulate import DENIED_COLUMN, DENIED_DATASET, answer, effective, model, row_filter

QUERY_TABLE = "crm.customers"
QUERY_COLUMNS = ["customer_id", "msisdn", "email", "birth_date", "country", "segment"]
QUERY_SEATS = ["analyst@GR", "fraud_investigator", "steward"]


def expected(e, seat: str, fqn: str, granted: frozenset[tuple[str, str]]) -> str:
    role = seat.split("@")[0]
    ds, table, path = fqn.split(".", 2)
    c = next((c for c in e.contracts if c.dataset == ds), None)
    if c is None:
        return DENIED_DATASET  # no contract: no dataset viewer is compiled for anyone
    if role not in c.readers and not ((seat, ds) in granted and role in c.marketplace.grantable_roles):
        return DENIED_DATASET
    col = c.tables[table].columns[path]
    if not col.classification.tagged:
        return "clear"
    m = col.masking.get(role)
    if m is None:
        return DENIED_COLUMN
    return "clear" if m.value == "clear" else PREDEFINED[m]


def expected_filter(e, seat: str, table: str) -> str | None:
    role, _, scope = seat.partition("@")
    ds, tname = table.split(".")
    c = next((c for c in e.contracts if c.dataset == ds), None)
    if c is None:
        return "TRUE"
    t = c.tables[tname]
    if t.row_access.column is None:
        return "TRUE"
    reach = set(c.readers) | set(c.marketplace.grantable_roles) | {"custodian"}
    if role not in reach:
        return None
    r = e.roles.roles[role]
    return f'{t.row_access.column} = "{scope}"' if r.scoped_by == t.row_access.column else "TRUE"


def evaluate() -> dict:
    e = pipeline.load()
    am = model(e.compiled["infra/estate/generated.tf.json"], e.compiled["infra/governance/generated.tf.json"])
    seats = [s for r in sorted(e.roles.roles) for s in e.roles.seats(r)]
    columns = sorted(am.column_tag)
    contracted = {c.dataset for c in e.contracts}
    # every grantable seat holding an approved grant on its dataset — what claim 6's flow can produce
    all_grants = frozenset(
        (s, c.dataset) for c in e.contracts for r in c.marketplace.grantable_roles for s in e.roles.seats(r)
    )
    mismatches, checked = [], 0
    for scenario, granted in (("standing", frozenset()), ("with approved grants", all_grants)):
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
    filters_checked = 0
    for table in sorted({".".join(c.split(".")[:2]) for c in columns}):
        for seat in seats:
            exp, got = expected_filter(e, seat, table), row_filter(am, seat, table)
            filters_checked += 1
            if exp != got:
                mismatches.append(
                    {"scenario": "row filter", "seat": seat, "column": table, "expected": exp, "compiled": got}
                )
    uncontracted = [c for c in columns if c.split(".")[0] not in contracted]
    leaks = [
        (s, c)
        for c in uncontracted
        for s in seats
        for g in (frozenset(), frozenset({(s, c.split(".")[0])}))  # even a (wrongly issued) grant must not open it
        if not effective(am, s, c, g).startswith("denied")
    ]

    rows = io.synthetic_rows(QUERY_TABLE)
    types = {f["name"]: f["type"] for f in io.harvest()[QUERY_TABLE]["fields"]}
    answers = [
        answer(
            am,
            s,
            QUERY_TABLE,
            QUERY_COLUMNS,
            rows,
            types,
            granted=all_grants if s == "fraud_investigator" else frozenset(),
        )
        for s in QUERY_SEATS
    ]
    gate = check(e.contracts, e.roles)
    return {
        "checked_column_decisions": checked,
        "checked_row_filters": filters_checked,
        "mismatches": mismatches,
        "uncontracted_columns": len(uncontracted),
        "uncontracted_leaks": leaks,
        "gate_findings": [f.to_dict() for f in gate],
        "query": {
            "sql": f"SELECT {', '.join(QUERY_COLUMNS)} FROM {QUERY_TABLE} ORDER BY customer_id LIMIT 5",
            "mode": "SIMULATED from compiled Terraform",
            "answers": answers,
        },
    }


def main() -> int:
    from steward.core.findings import Finding

    r = evaluate()
    print(
        f"compiled vs contract: {r['checked_column_decisions']} seat×column decisions, {r['checked_row_filters']} seat×table row filters"
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
            print(f"  {a['seat']:20} {a['error']}")
        else:
            first = a["rows"][0] if a["rows"] else {}
            print(
                f"  {a['seat']:20} rows {a['rows_visible']}/{a['rows_total']}  msisdn={first.get('msisdn')!s:.16}  email={first.get('email')}  birth_date={first.get('birth_date')}"
            )
    if r["mismatches"] or r["uncontracted_leaks"] or code:
        print("FAIL claim 2 (compiled side)")
        return 1
    print("ok claim 2 (compiled side): the compiled controls are exactly what the contracts imply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
