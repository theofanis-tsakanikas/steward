#!/usr/bin/env python3
"""Gate (doctrine 4): every contract changed since BASE bumped its version and kept its history.

    python scripts/check_contract_versions.py [--base REF]

BASE defaults to $STEWARD_BASE_REF, else origin/main. If BASE does not exist (a fresh clone with no
remote) the check says so and passes — CI always provides it.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from steward import io  # noqa: E402
from steward.core.versioning import compare  # noqa: E402


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("STEWARD_BASE_REF", "origin/main"))
    args = ap.parse_args(argv)
    if git("rev-parse", "--verify", "--quiet", args.base).returncode:
        print(f"skip contract-versions: base {args.base!r} not available")
        return 0
    listed = git("ls-tree", "--name-only", args.base, "contracts/").stdout.split()
    old = {
        Path(p).stem: yaml.safe_load(git("show", f"{args.base}:{p}").stdout)
        for p in listed
        if p.endswith(".yaml") and not Path(p).name.startswith("_")
    }
    new = io.contract_docs()
    findings = [f for name in sorted(set(old) | set(new)) for f in compare(name, old.get(name), new.get(name))]
    for f in findings:
        print(f.line())
    if findings:
        print(f"FAIL contract-versions: {len(findings)} finding(s) against {args.base}")
        return 1
    print(f"ok contract-versions: {len(new)} contract(s) consistent with {args.base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
