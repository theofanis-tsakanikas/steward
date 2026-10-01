"""Claim 5 — a failing row is quarantined with its rule and routed to its owner, never dropped.

A. quarantined rows vs the planted defects (table, source offset, kind): exact match required
B. reconciliation from three independent counts: source lines counted before the rules ran, loaded
   and quarantined counted from what was written — source = loaded + quarantined for every table
C. every quarantine record carries rule ids, row key, run id, owner and the row itself
D. freshness evaluated against the synthetic anchor date
"""

from __future__ import annotations

import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from steward import pipeline, quality_run
from steward.core.findings import Finding, report
from steward.core.gate_quality import gate

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import load_planted

FIXED_RUN = datetime(2026, 9, 30, 6, 0, tzinfo=UTC)


def evaluate(out: Path | None = None) -> dict:
    e = pipeline.load()
    today = pipeline.synthetic_anchor()
    out = out or Path(tempfile.mkdtemp(prefix="steward-q-"))
    summary = quality_run.load_all(e.contracts, out, today, when=FIXED_RUN)
    tables = sorted(summary["tables"])
    counts, quarantine = quality_run.read_destination(out, tables)

    planted = {(d["table"], d["offset"], d["kind"]) for d in load_planted()["quality_defects"]}
    got = {(t, r["offset"], f["kind"]) for t, recs in quarantine.items() for r in recs for f in r["failures"]}
    findings = gate(counts, quarantine) + [Finding(**f) for t in summary["tables"].values() for f in t["findings"]]
    by_owner = Counter(r["routed_to"] for recs in quarantine.values() for r in recs)
    by_rule = Counter(rid for recs in quarantine.values() for r in recs for rid in r["rule_ids"])
    return {
        "today": today.isoformat(),
        "counts": counts,
        "planted": len(planted),
        "missed": sorted(map(list, planted - got)),
        "unexpected": sorted(map(list, got - planted)),
        "routed_to": dict(sorted(by_owner.items())),
        "by_rule": dict(sorted(by_rule.items())),
        "quarantine_sample": [{k: v for k, v in r.items() if k != "row"} for recs in quarantine.values() for r in recs][
            :20
        ],
        "findings": [f.to_dict() for f in findings],
    }


def main() -> int:
    r = evaluate()
    for t, c in r["counts"].items():
        mark = "=" if c["source"] == c["loaded"] + c["quarantined"] else "≠"
        print(f"  {t:30} source {c['source']:5} {mark} loaded {c['loaded']:5} + quarantined {c['quarantined']:2}")
    print(f"planted defects {r['planted']}: missed {len(r['missed'])}, unexpected {len(r['unexpected'])}")
    for m in r["missed"]:
        print(f"  MISSED {m[0]} offset {m[1]} {m[2]} — a planted defect that was not quarantined")
    for m in r["unexpected"]:
        print(f"  UNEXPECTED {m[0]} offset {m[1]} {m[2]} — quarantined, but nothing was planted there")
    print(f"routed to: {r['routed_to']}")
    print(f"by rule:   {r['by_rule']}")
    code, lines = report("quality", [Finding(**f) for f in r["findings"]])
    print("\n".join("  " + ln for ln in lines))
    if r["missed"] or r["unexpected"] or code:
        print("FAIL claim 5")
        return 1
    print("ok claim 5: every planted defect quarantined with its rule and owner; nothing lost")
    return 0


if __name__ == "__main__":
    sys.exit(main())
