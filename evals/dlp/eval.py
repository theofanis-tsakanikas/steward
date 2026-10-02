"""Claim 1, live — Sensitive Data Protection against the planted ground truth and against the contracts.

Reads `evidence/live/dlp.json` (steward capture --what dlp). Three parts, each with its n:
  A. the CONTROL sample (the generator's own rows, every column, through the same template) vs the planted manifest:
     which planted (column, kind) pairs did DLP find, which did it miss, what did it find that nothing planted
  B. the live untagged columns: DLP must find nothing there (doctrine 7), and no answer may be truncated
  C. the verdict of core/live_assurance.verify_dlp on the whole document
Honest limit printed with the result: the control is the same generator as claim 1's detector eval, so recall here
measures the template on that data, not Sensitive Data Protection in the wild; and policy-tagged columns are not
inspected live (no reader holds them), so DLP's opinion on them comes from the control only.
No capture committed: nothing to judge (exit 0).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import REPO, load_planted
from steward import io, pipeline
from steward.core import live_assurance as la
from steward.core.classify import detect
from steward.core.findings import report
from steward.pipeline import synthetic_anchor


def evaluate() -> dict | None:
    path = REPO / "evidence" / "live" / "dlp.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())["data"]
    e = pipeline.load()
    planted = {(p["column"], k) for p in load_planted()["pii"] for k in p["kinds"]}
    found = {(f"{r['table']}.{r['column']}", r["kind"]) for r in data["control"]["findings"] if r["kind"] is not None}
    n = data["control"]["rows_per_table"]
    core = {(d.column, k) for d in detect(io.synthetic_columns(limit=n), synthetic_anchor()) for k in d.kinds}
    other = sorted(
        {(f"{r['table']}.{r['column']}", r["info_type"]) for r in data["control"]["findings"] if r["kind"] is None}
        | {(c, k) for (c, k) in found - planted}
    )
    findings = la.verify_dlp(data, e.compiled_tags, set(e.harvest))
    return {
        "planted": len(planted),
        "found": sorted(map(list, planted & found)),
        "missed": sorted(map(list, planted - found)),
        "core_found": sorted(map(list, planted & core)),
        "core_missed": sorted(map(list, planted - core)),
        "beyond_planted": [list(x) for x in other],
        "live_untagged_findings": len(data["findings"]),
        "tables": len(data["tables"]),
        "control_rows_per_table": data["control"]["rows_per_table"],
        "findings": [f.to_dict() for f in findings],
    }


def main() -> int:
    r = evaluate()
    if r is None:
        print("no evidence/live/dlp.json: nothing captured yet")
        return 0
    print(
        f"control sample ({r['control_rows_per_table']} rows/table) vs planted manifest, n={r['planted']} (column, kind) pairs"
    )
    print(f"  DLP  found {len(r['found'])}, missed {len(r['missed'])}")
    print(f"  core found {len(r['core_found'])}, missed {len(r['core_missed'])} (values only, no contract)")
    for c, k in r["missed"]:
        print(f"  MISSED {c} {k} — planted, the template did not report it (a limit of DLP, listed, not hidden)")
    for c, k in r["beyond_planted"]:
        print(f"  BEYOND {c} {k} — DLP found something nothing planted (stricter wins: the contract must tag it)")
    print(f"live: {r['tables']} tables inspected, {r['live_untagged_findings']} finding(s) in untagged columns")
    from steward.core.findings import Finding

    code, lines = report("dlp", [Finding(**f) for f in r["findings"]])
    print("\n".join("  " + ln for ln in lines))
    if code:
        print("FAIL claim 1 (live)")
        return 1
    print("ok claim 1 (live): no personal data DLP can see sits in a column the contracts leave untagged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
