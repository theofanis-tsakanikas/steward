"""Claim 5, live — Dataplex data-quality scans against the offline quality engine.

Reads `evidence/live/dataplex.json` (steward capture --what dataplex). For each rule: Dataplex's failed-row count vs the
number of rows the offline engine quarantined for that rule (evals/quality's own result). The two engines are written
independently (Dataplex's rule semantics were compiled from the contract; the offline engine is core/quality.py), so
agreement is evidence and disagreement is a finding, not a merge.
No capture committed: nothing to judge (exit 0).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import REPO
from steward import live
from steward.core.findings import Finding, report


def evaluate() -> dict | None:
    path = REPO / "evidence" / "live" / "dataplex.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())["data"]
    quality = json.loads((REPO / "evidence" / "fixture" / "quality.json").read_text())["data"]
    findings = live.verify_dataplex(data)  # the same judge as the gate, with the rules the compiled scans carry
    rules = [
        {"scan": s["scan"], "rule": r["rule"], "evaluated": r["evaluated"], "failed": r["failed_rows"]}
        for s in data["scans"]
        for r in s["rules"]
    ]
    return {
        "scans": len(data["scans"]),
        "rules": rules,
        "offline": dict(sorted(quality["by_rule"].items())),
        "findings": [f.to_dict() for f in findings],
    }


def main() -> int:
    r = evaluate()
    if r is None:
        print("no evidence/live/dataplex.json: nothing captured yet")
        return 0
    print(f"{r['scans']} scans, {len(r['rules'])} rules; offline engine quarantined by rule: {r['offline']}")
    for x in r["rules"]:
        if x["failed"]:
            print(f"  {x['scan']:36} {x['rule']:10} failed {x['failed']} of {x['evaluated']}")
    code, lines = report("dataplex", [Finding(**f) for f in r["findings"]])
    print("\n".join("  " + ln for ln in lines))
    if code:
        print("FAIL claim 5 (live)")
        return 1
    print("ok claim 5 (live): Dataplex and the offline engine fail the same number of rows for every comparable rule")
    return 0


if __name__ == "__main__":
    sys.exit(main())
