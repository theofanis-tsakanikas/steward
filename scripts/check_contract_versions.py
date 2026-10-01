#!/usr/bin/env python3
"""Gate (doctrine 4): every contract changed since BASE bumped its version and kept its history.

    python scripts/check_contract_versions.py [--base REF]

BASE comes from --base, else $STEWARD_BASE_REF (CI sets it: the PR base, or the push's `before`),
else origin/main. Fails closed:
  - an explicitly given base that does not resolve to a commit is an error, not a skip;
  - an all-zero base (the first push of a branch) compares with HEAD~1, the commit being replaced;
  - only the implicit default (origin/main) may be absent, on a fresh clone with no remote.
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


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def resolve(repo: Path, ref: str) -> str | None:
    r = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return r.stdout.strip() if r.returncode == 0 else None


def main(argv: list[str] | None = None, repo: Path = REPO) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=None)
    args = ap.parse_args(argv)
    explicit = args.base or os.environ.get("STEWARD_BASE_REF") or None
    base = explicit or "origin/main"
    if set(base) == {"0"}:
        base = "HEAD~1"
        print("contract-versions: all-zero base (first push) — comparing with HEAD~1")
    sha = resolve(repo, base)
    if sha is None:
        if explicit:
            print(f"FAIL contract-versions: base {base!r} does not resolve to a commit")
            return 1
        print(f"skip contract-versions: default base {base!r} not available (no remote)")
        return 0
    tree = git(repo, "ls-tree", "--name-only", sha, "contracts/")
    if tree.returncode:
        print(f"FAIL contract-versions: cannot list contracts at {base}: {tree.stderr.strip()}")
        return 1
    old = {
        Path(p).stem: yaml.safe_load(git(repo, "show", f"{sha}:{p}").stdout)
        for p in tree.stdout.split()
        if p.endswith(".yaml") and not Path(p).name.startswith("_")
    }
    new = io.contract_docs(repo / "contracts")
    findings = [f for name in sorted(set(old) | set(new)) for f in compare(name, old.get(name), new.get(name))]
    for f in findings:
        print(f.line())
    if findings:
        print(f"FAIL contract-versions: {len(findings)} finding(s) against {base}")
        return 1
    print(f"ok contract-versions: {len(new)} contract(s) consistent with {base} ({sha[:8]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
