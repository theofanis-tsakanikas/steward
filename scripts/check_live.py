#!/usr/bin/env python3
"""Gate: re-judge the committed live captures, offline.

`evidence/live/<name>.json` is what a running estate answered (steward capture). Each file is judged here by a core
function against what the repository says it should be, with no account and no network:

  access    the three role transcripts vs the compiled Terraform and the stored rows   (claim 2)
  iam       the dataset IAM snapshot vs the marketplace ledger: approvals, expiry       (claim 6)
  dlp       Sensitive Data Protection's findings vs the contracts' policy tags          (claim 1)
  dataplex  the quality scans' per-rule failed rows vs the offline quality engine       (claim 5)
  audit     the access-review query over the audit sink answered                        (claim 6)

The digest of each file is `steward evidence-check`'s business (EVIDENCE_DIGEST_MISMATCH); this gate reads the payload
as committed, so a mutation of its content reaches the verdict it is meant to.
No `evidence/live/` directory: nothing to judge, exit 0 (the demo says it runs from the fixture).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from steward import io, live, pipeline  # noqa: E402
from steward.core import live_assurance  # noqa: E402
from steward.core.findings import Finding, report  # noqa: E402
from steward.core.marketplace import decide, gate, load_ledger  # noqa: E402

LIVE = REPO / "evidence" / "live"


def _data(name: str) -> dict | None:
    path = LIVE / f"{name}.json"
    return json.loads(path.read_text())["data"] if path.exists() else None


def verify_iam(e, snap: dict) -> list[Finding]:
    ledger, lf = load_ledger(e.ledger)
    if ledger is None:
        return lf
    out = gate(snap, decide(ledger, e.contracts, e.roles), e.contracts, e.roles)
    # a member the demo does not know is not silently ignored: it is listed in the evidence, and it is a finding here
    out += [
        Finding(
            "LIVE_IAM_UNKNOWN_MEMBER",
            "iam",
            f"{m['dataset']} {m['member']}",
            f"{m['role']} held by a principal that is neither a seat nor a requester",
            severity="warn",
        )
        for m in snap.get("other_members", [])
    ]
    return out


def verify_audit(data: dict) -> list[Finding]:
    if data.get("outcome") == "error":
        return [Finding("LIVE_AUDIT_ERROR", "audit", "access review", str(data.get("error", "no message"))[:200])]
    return []


def judge() -> tuple[list[Finding], list[str]]:
    seen: list[str] = []
    out: list[Finding] = []
    e = None
    for name in ("access", "iam", "dlp", "dataplex", "audit"):
        data = _data(name)
        if data is None:
            continue
        e = e or pipeline.load()
        seen.append(name)
        if name == "access":
            out += live.verify_access(data, e)
        elif name == "iam":
            out += verify_iam(e, data)
        elif name == "dlp":
            out += live_assurance.verify_dlp(data, e.compiled_tags, set(e.harvest))
        elif name == "dataplex":
            quality = json.loads((REPO / "evidence" / "fixture" / "quality.json").read_text())["data"]
            counts = {t: c["source"] for t, c in quality["counts"].items()}
            out += live_assurance.verify_dataplex(data, counts, quality["by_rule"])
        else:
            out += verify_audit(data)
    return out, seen


def main() -> int:
    if not LIVE.is_dir() or not any(LIVE.glob("*.json")):
        print("ok live: no evidence/live/ — nothing captured yet; the demo runs from the fixture")
        return 0
    findings, seen = judge()
    print(f"live captures judged: {', '.join(seen) or 'none'} (from {io.REPO.name}/evidence/live)")
    code, lines = report("live", findings)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
