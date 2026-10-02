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
from steward.core.findings import Finding, report  # noqa: E402

LIVE = REPO / "evidence" / "live"


def _data(name: str) -> dict | None:
    path = LIVE / f"{name}.json"
    return json.loads(path.read_text())["data"] if path.exists() else None


def judge() -> tuple[list[Finding], list[str]]:
    seen: list[str] = []
    out: list[Finding] = []
    e = None
    held = {p.stem for p in LIVE.glob("*.json")} if LIVE.is_dir() else set()
    if held:
        for name in live.VERIFY:
            if name not in held:
                out.append(
                    Finding(
                        "LIVE_CAPTURE_MISSING",
                        name,
                        name,
                        "VERIFY names this capture and it is not on disk",
                    )
                )
    for name, verify in live.VERIFY.items():
        data = _data(name)
        if data is None:
            continue
        e = e or pipeline.load()
        seen.append(name)
        out += verify(data, e)
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
