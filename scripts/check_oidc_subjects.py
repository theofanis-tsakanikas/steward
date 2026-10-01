#!/usr/bin/env python3
"""The Workload Identity Federation trust is the whole security boundary; this keeps it written the way it was meant.

Refused:
  OIDC_WILDCARD         a `*` in infra/bootstrap/wif.tf outside a comment (a trust that matches by pattern)
  OIDC_REPO_UNPINNED    the trust condition does not pin the repository id (`assertion.repository_id ==`)
  OIDC_OWNER_UNPINNED   ... or the owner id (`assertion.repository_owner_id ==`)
  OIDC_NO_ENVIRONMENT   ... or does not require a deploy/destroy environment (`assertion.environment in`)
  OIDC_FEDERATION_OPEN  the principalSet that may become the deployer is not scoped to `attribute.repository_id/<id>`
  KEY_FORBIDDEN         any google_service_account_key anywhere under infra/ (no long-lived credentials, CLAUDE.md)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WIF = REPO / "infra" / "bootstrap" / "wif.tf"


def _code(text: str) -> list[tuple[int, str]]:
    """(line number, line) without comments."""
    return [(i, ln.split("#", 1)[0]) for i, ln in enumerate(text.splitlines(), 1) if ln.split("#", 1)[0].strip()]


def problems(root: Path = REPO) -> list[str]:
    out: list[str] = []
    wif = root / "infra" / "bootstrap" / "wif.tf"
    rel = wif.relative_to(root)
    if not wif.exists():
        return [f"ERROR OIDC_NO_TRUST {rel} — the bootstrap layer has no Workload Identity trust"]
    code = _code(wif.read_text())
    for n, ln in code:
        if "*" in ln:
            out.append(f"ERROR OIDC_WILDCARD {rel}:{n} — a trust must not match by pattern: {ln.strip()}")
    body = "\n".join(ln for _, ln in code)
    for needle, name, what in (
        ("assertion.repository_id ==", "OIDC_REPO_UNPINNED", "the repository id"),
        ("assertion.repository_owner_id ==", "OIDC_OWNER_UNPINNED", "the owner id"),
        ("assertion.environment in", "OIDC_NO_ENVIRONMENT", "a deploy/destroy environment"),
    ):
        if needle not in body:
            out.append(f"ERROR {name} {rel} — the trust condition does not pin {what}")
    m = re.search(r'member\s*=\s*"principalSet://[^"]*"', body)
    if not m or "/attribute.repository_id/${var.github_repository_id}" not in m.group(0):
        out.append(f"ERROR OIDC_FEDERATION_OPEN {rel} — the principalSet must end in attribute.repository_id/<id>")
    for tf in sorted((root / "infra").rglob("*.tf*")):
        if "google_service_account_key" in tf.read_text():
            out.append(f"ERROR KEY_FORBIDDEN {tf.relative_to(root)} — no service-account key may exist")
    return out


def main() -> int:
    found = problems()
    print("\n".join(found))
    if found:
        print(f"FAIL oidc-subjects: {len(found)} blocking finding(s)")
        return 1
    print("ok oidc-subjects: the trust pins repository, owner and environment; no wildcard; no key")
    return 0


if __name__ == "__main__":
    sys.exit(main())
