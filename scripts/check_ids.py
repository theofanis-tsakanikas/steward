#!/usr/bin/env python3
"""Refuse a tree that contains this project's GCP identifiers (P1: they must not ship).

Identifiers are read from the git-ignored `infra/bootstrap/terraform.tfvars` and from the
environment — never hard-coded here. A finding names the file, never the identifier.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TFVARS = REPO / "infra" / "bootstrap" / "terraform.tfvars"
PLACEHOLDERS = {"", "change-me", "0", "000000-000000-000000", "you@example.com"}
# Keys whose values are this project's identifiers. github_owner / github_repo are the public name.
ID_KEYS = {
    "project_id",
    "project_number",
    "org_id",
    "organization_id",
    "billing_account_id",
    "github_owner_id",
    "github_repository_id",
}
ENV_KEYS = (
    "STEWARD_PROJECT_ID",
    "GCP_PROJECT_ID",
    "STEWARD_PROJECT_NUMBER",
    "GCP_PROJECT_NUMBER",
    "STEWARD_ORG_ID",
    "GCP_ORG_ID",
    "STEWARD_BILLING_ACCOUNT",
    "GCP_BILLING_ACCOUNT",
)
# gate-proof plants a value here; empty in the committed tree so the canary is not itself a leak.
EXTRA_IDS: tuple[str, ...] = ()
SKIP_SUFFIX = {".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".pyc"}
# PNGs are scanned as text: a console screenshot that still holds a project id is a leak.
CANARY = "x-planted-" + "project-number-000"
SKIP_NAMES = {"terraform.tfvars", "terraform.tfstate", "terraform.tfstate.backup"}
_ASSIGN = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"([^"]*)"\s*$')


def _keep(value: str) -> bool:
    v = value.strip()
    return len(v) >= 6 and v.lower() not in PLACEHOLDERS


def identifiers(
    env: dict[str, str] | None = None, tfvars: Path | None = TFVARS, extra: tuple[str, ...] = EXTRA_IDS
) -> set[str]:
    """The identifiers this check looks for. Empty means nothing to refuse — a stranger's clone has none."""
    out: set[str] = {e for e in extra if _keep(e)}
    for key in ENV_KEYS:
        val = (env if env is not None else os.environ).get(key, "")
        if _keep(val):
            out.add(val.strip())
    path = tfvars if tfvars is not None else TFVARS
    if path.is_file():
        for raw in path.read_text().splitlines():
            line = raw.split("#", 1)[0].strip()
            if line.startswith("alert_emails"):
                for email in re.findall(r'"([^"]+@[^"]+)"', line):
                    if _keep(email):
                        out.add(email)
                continue
            m = _ASSIGN.match(line)
            if m and m.group(1) in ID_KEYS and _keep(m.group(2)):
                out.add(m.group(2))
    return out


def tracked_files(root: Path) -> list[Path]:
    """git ls-files; terraform.tfvars is git-ignored and so never listed."""
    r = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    return [root / p.decode() for p in r.stdout.split(b"\0") if p]


def _scan_list(root: Path) -> list[Path]:
    try:
        return tracked_files(root)
    except (subprocess.CalledProcessError, FileNotFoundError):
        skip_dirs = {".git", ".venv", ".terraform", "__pycache__", ".pytest_cache", ".ruff_cache", "out"}
        out: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            out.extend(Path(dirpath) / n for n in filenames)
        return out


def hits(root: Path, ids: set[str], files: list[Path] | None = None) -> list[str]:
    """Paths that contain an identifier. The identifier itself is never returned."""
    if not ids:
        return []
    out = []
    for path in files if files is not None else _scan_list(root):
        if path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIX or not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if any(i in text for i in ids):
            out.append(str(path.relative_to(root)))
    return sorted(out)


def problems(root: Path = REPO, env: dict[str, str] | None = None, tfvars: Path | None = TFVARS) -> list[str]:
    found = hits(root, identifiers(env=env, tfvars=tfvars))
    return [
        f"ERROR ID_IN_TREE {p} — a project/org/billing identifier from terraform.tfvars or the environment"
        for p in found
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", action="append", default=[], help="extra identifier (used by gate-proof; never a real id)")
    args = ap.parse_args(argv)
    live = identifiers(extra=(*EXTRA_IDS, *args.id))
    if os.environ.get("GITHUB_ACTIONS") == "true" and not live:
        print("ERROR ID_UNCONFIGURED CI has no identifiers to refuse — set the STEWARD_* secrets")
        return 1
    ids = live | {CANARY}
    found = hits(REPO, ids)
    for p in found:
        print(f"ERROR ID_IN_TREE {p} — a project/org/billing identifier from terraform.tfvars or the environment")
    if found:
        print(f"FAIL ids: {len(found)} tracked file(s) contain a live identifier")
        return 1
    src = "terraform.tfvars/env" if live else "no live identifiers (canary only)"
    print(f"ok ids: {len(ids)} identifier(s) from {src}, 0 hits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
