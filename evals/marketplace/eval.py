"""Claim 6 — access is requested, approved by a named human, and expires.

A. every ledger request has the outcome its decision deserves (the ledger's comments say why)
B. the clean snapshot (what the compiled IaC would bind) passes the gate
C. the drift snapshot (clean + planted hand-made bindings) raises exactly the planted findings
D. "now" is the snapshot's capture time: the same drift snapshot captured before R-009 lapsed is clean
   of GRANT_EXPIRED_PRESENT — the evaluator reads time from evidence, never from a clock
E. report lifecycle on the Looker usage fixture (labelled FIXTURE, D3)
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import yaml

from steward import pipeline
from steward.core.findings import Finding, report
from steward.core.lifecycle import states
from steward.core.marketplace import decide, gate

HERE = Path(__file__).resolve().parent
CAPTURED = "2026-09-30T18:00:00Z"
EXPECTED = {
    "R-001": ("granted", []),
    "R-002": ("granted", []),
    "R-003": ("refused", ["DURATION_EXCEEDS_MAX"]),
    "R-004": (
        "refused",
        ["SELF_APPROVAL"],
    ),  # the approver owns network and sits in analyst@IT: only this check stops it
    "R-005": ("refused", ["SERVICE_ACCOUNT_APPROVAL"]),
    "R-006": ("refused", ["ROLE_NOT_GRANTABLE"]),
    "R-007": ("denied-no-decision", []),
    "R-008": ("refused", ["APPROVER_NOT_AUTHORISED"]),
    "R-009": ("granted", []),  # approved properly — and expired by as_of, so not compiled
    "R-010": ("refused", ["DATASET_NOT_LISTED"]),
    "R-011": ("refused", ["REQUESTER_NOT_IN_SEAT"]),
}


def evaluate() -> dict:
    e = pipeline.load()
    outcomes = decide(e.ledger, e.contracts, e.roles)
    got = {o.request["id"]: (o.status, sorted(r.code for r in o.reasons if r.severity == "error")) for o in outcomes}
    wrong = {
        rid: {"expected": exp, "got": got.get(rid)}
        for rid, exp in EXPECTED.items()
        if got.get(rid) != (exp[0], sorted(exp[1]))
    }
    # a grant is bound to the person who asked — read back from the compiled Terraform, not from Outcome
    compiled = e.compiled["infra/marketplace/generated.tf.json"]["resource"].get("google_bigquery_dataset_iam_member", {})
    for o in outcomes:
        node = compiled.get(o.request["id"].lower().replace("-", "_"))
        if node is not None and node["member"] != f'${{var.principals["{o.request["requester"]}"]}}':
            wrong[o.request["id"]] = {"expected": f"member {o.request['requester']}", "got": f"member {node['member']}"}

    clean = pipeline.iam_snapshot(e, CAPTURED)
    clean_findings = gate(clean, outcomes, e.contracts, e.roles)
    planted = yaml.safe_load((HERE / "planted_drift.yaml").read_text())["bindings"]
    drift = copy.deepcopy(clean)
    drift["bindings"] += [{k: v for k, v in b.items() if k not in ("expect", "why")} for b in planted]
    drift_findings = gate(drift, outcomes, e.contracts, e.roles)
    expect = sorted((b["expect"], f"{b['dataset']}:{b['member']}") for b in planted)
    got_drift = sorted((f.code, f.target) for f in drift_findings if f.blocking)
    early = dict(drift, captured_at="2026-09-10T00:00:00Z")
    early_codes = {
        f.code
        for f in gate(early, outcomes, e.contracts, e.roles)
        if f.target == "network:user:anna.pappas@halverra.example"
    }

    usage = json.loads((HERE / "looker_usage.json").read_text())
    return {
        "captured_at": CAPTURED,
        "outcomes": [o.to_dict() for o in outcomes],
        "outcome_mismatches": wrong,
        "clean_snapshot": clean,
        "clean_findings": [f.to_dict() for f in clean_findings],
        "drift_planted": planted,
        "drift_expected": expect,
        "drift_got": got_drift,
        "now_from_evidence": {
            "early_capture": early["captured_at"],
            "expired_flagged_early": "GRANT_EXPIRED_PRESENT" in early_codes,
        },
        "lifecycle": {"mode": usage["_mode"], "captured_at": usage["captured_at"], "dashboards": states(usage)},
    }


def main() -> int:
    r = evaluate()
    for o in r["outcomes"]:
        reasons = ", ".join(x["code"] for x in o["reasons"]) or "-"
        print(
            f"  {o['request']['id']} {o['request']['seat']:20} → {o['request']['dataset']:8} {o['status']:20} {reasons}  {o['expires_at'] or ''}"
        )
    for rid, m in r["outcome_mismatches"].items():
        print(f"  MISMATCH {rid}: expected {m['expected']} got {m['got']}")
    code, lines = report("marketplace (clean snapshot)", [Finding(**f) for f in r["clean_findings"]])
    print("\n".join("  " + ln for ln in lines))
    print(f"drift snapshot: expected {r['drift_expected']}")
    print(f"                got      {r['drift_got']}")
    print(
        f"now from evidence: the same expired binding captured at {r['now_from_evidence']['early_capture']} flagged? {r['now_from_evidence']['expired_flagged_early']}"
    )
    for d in r["lifecycle"]["dashboards"]:
        print(f"  dashboard {d['dashboard']:18} idle {d['idle_days']!s:>4} d  {d['state']:13} {d['action']}")
    ok = (
        not r["outcome_mismatches"]
        and code == 0
        and r["drift_expected"] == r["drift_got"]
        and not r["now_from_evidence"]["expired_flagged_early"]
    )
    print("ok claim 6: requests, named approvals, expiry and drift all as declared" if ok else "FAIL claim 6")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
