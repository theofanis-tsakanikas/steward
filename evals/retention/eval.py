"""Claim 7 — retention is declared, enforced and evidenced.

A. every contracted table has exactly one compiled mechanism equal to its declaration, read back from
   the compiled Terraform (partition expiration ms, or one daily DELETE with the declared column and
   period), its quarantine table too, and a landing-bucket lifecycle rule per dataset
B. every dataset's time travel is the 48 h the caveat promises
C. the report's first line is the time-travel / fail-safe caveat; the uncontracted legacy table is
   listed as NO DECLARATION with its waiver and expiry, never silently omitted
D. live evidence (partition expiration read from INFORMATION_SCHEMA) arrives with T011/T017; until then
   every row says "compiled (not yet evidenced live)"
"""

from __future__ import annotations

import sys

from steward import io, pipeline
from steward.core import retention
from steward.core.findings import report


def evaluate() -> dict:
    e = pipeline.load()
    r = retention.report(e.contracts, e.harvest, io.waivers_doc().get("waivers", []))
    findings = retention.gate(
        e.contracts,
        e.compiled["infra/estate/generated.tf.json"],
        e.compiled["infra/governance/generated.tf.json"],
        e.harvest,
    )
    return {"report": r, "findings": [f.to_dict() for f in findings]}


def main() -> int:
    from steward.core.findings import Finding

    r = evaluate()
    rep = r["report"]
    first = rep["caveat"]
    ok_caveat = first.startswith("Deletion is not immediate") and "fail-safe" in first and "time travel" in first
    print(
        f"first line: {first}"
        if ok_caveat
        else "CAVEAT_MISSING first line — the report must open with the time-travel / fail-safe caveat"
    )
    for row in rep["rows"]:
        print(
            f"  {row['dataset']}.{row['table']:28} {row['period_days']!s:>5} d  {row['mechanism']['kind']:28} {row['status']}"
        )
    unlisted = [row for row in rep["rows"] if row["dataset"] == "legacy"]
    code, lines = report("retention", [Finding(**f) for f in r["findings"]])
    print("\n".join("  " + ln for ln in lines))
    ok = ok_caveat and code == 0 and len(unlisted) == 1 and "waived" in unlisted[0]["status"]
    print("ok claim 7: declared, compiled exactly, caveat first, legacy listed" if ok else "FAIL claim 7")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
