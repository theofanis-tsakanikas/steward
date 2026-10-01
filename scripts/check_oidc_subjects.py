#!/usr/bin/env python3
"""The Workload Identity Federation trust is the whole security boundary. This compares what is written with
what is meant, clause by clause, and looks at every file that could widen it — not at one file for a few words.

Refused:
  OIDC_NO_TRUST         infra/bootstrap/wif.tf is missing, or has no trust_condition
  OIDC_CLAUSES          the trust clauses are not exactly the expected set (missing, extra or reworded)
  OIDC_JOINER           the clauses are not joined by AND (an OR would make any one of them enough)
  OIDC_ENVS             the trusted environments are not exactly deploy and destroy
  OIDC_UNWIRED          the provider's attribute_condition is not `local.trust_condition` (a trust that is
                        written but not applied)
  OIDC_PATTERN          a wildcard or pattern operator (`*`, startsWith, endsWith, matches, contains, `||`)
                        in the trust file: every value is an exact match
  OIDC_FEDERATION_OPEN  who may become a CI service account is anything other than: the `deploy` environment
                        for the deployer, the `destroy` environment for the destroyer — or a
                        workloadIdentityUser grant exists outside wif.tf
  OIDC_PUBLIC           allUsers / allAuthenticatedUsers anywhere under infra/
  OIDC_EXTRA_PROVIDER   a second workload identity pool or provider (a second door)
  KEY_FORBIDDEN         a service-account key resource under infra/, or a command that mints one in a workflow
                        (no long-lived credentials, CLAUDE.md)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

EXPECTED_CLAUSES = [
    "assertion.repository_owner_id == '${var.github_owner_id}'",
    "assertion.repository_id == '${var.github_repository_id}'",
    "assertion.repository == '${var.github_owner}/${var.github_repo}'",
    "assertion.ref == 'refs/heads/main'",
    """assertion.environment in [${join(", ", [for e in local.trusted_environments : "'${e}'"])}]""",
]
EXPECTED_ENVS = ["deploy", "destroy"]
EXPECTED_FEDERATION = {  # resource name -> (service account, the one environment that may become it)
    "deployer_federation": ("deployer", "deploy"),
    "destroyer_federation": ("destroyer", "destroy"),
}
PATTERN = re.compile(r"\*|startsWith|endsWith|matches\(|contains\(|\|\|")


def _code(text: str) -> str:
    """The text without `#` comments."""
    return "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())


def _block(body: str, header: str) -> str | None:
    """The text of the `{...}` block that follows `header` (balanced braces)."""
    i = body.find(header)
    if i < 0:
        return None
    j = body.index("{", i)
    depth = 0
    for k in range(j, len(body)):
        depth += {"{": 1, "}": -1}.get(body[k], 0)
        if depth == 0:
            return body[j : k + 1]
    return None


def problems(root: Path = REPO) -> list[str]:
    out: list[str] = []
    infra = root / "infra"
    wif = infra / "bootstrap" / "wif.tf"
    rel = "infra/bootstrap/wif.tf"
    if not wif.exists():
        return [f"ERROR OIDC_NO_TRUST {rel} — the bootstrap layer has no Workload Identity trust"]
    body = _code(wif.read_text())

    m = re.search(r"trust_condition\s*=\s*join\(\s*\"([^\"]*)\"\s*,\s*\[(.*?)\n\s*\]\s*\)", body, re.S)
    if not m:
        out.append(f"ERROR OIDC_NO_TRUST {rel} — no `trust_condition = join(...)` found")
    else:
        if m.group(1) != " && ":
            out.append(f"ERROR OIDC_JOINER {rel} — clauses are joined by {m.group(1)!r}, not ' && '")
        found = [ln.strip().rstrip(",").strip() for ln in m.group(2).splitlines() if ln.strip()]
        found = [c[1:-1] if c.startswith('"') and c.endswith('"') else c for c in found]
        for c in EXPECTED_CLAUSES:
            if c not in found:
                out.append(f"ERROR OIDC_CLAUSES {rel} — expected clause missing or reworded: {c}")
        for c in found:
            if c not in EXPECTED_CLAUSES:
                out.append(f"ERROR OIDC_CLAUSES {rel} — unexpected clause: {c}")
    envs = re.search(r"trusted_environments\s*=\s*\[(.*?)\]", body, re.S)
    got = re.findall(r'"([^"]*)"', envs.group(1)) if envs else None
    if got != EXPECTED_ENVS:
        out.append(f"ERROR OIDC_ENVS {rel} — trusted_environments is {got}, expected {EXPECTED_ENVS}")
    if not re.search(r"^\s*attribute_condition\s*=\s*local\.trust_condition\s*$", body, re.M):
        out.append(f"ERROR OIDC_UNWIRED {rel} — the provider's attribute_condition is not local.trust_condition")
    for n, ln in enumerate(body.splitlines(), 1):
        if PATTERN.search(ln):
            out.append(f"ERROR OIDC_PATTERN {rel}:{n} — an exact match is required, not a pattern: {ln.strip()}")

    prefix = "${google_iam_workload_identity_pool.github.name}"
    for name, (sa, env) in EXPECTED_FEDERATION.items():
        blk = _block(body, f'resource "google_service_account_iam_member" "{name}"')
        want_member = f'"principalSet://iam.googleapis.com/{prefix}/attribute.environment/{env}"'
        ok = (
            blk is not None
            and re.search(rf"service_account_id\s*=\s*google_service_account\.{sa}\.name", blk)
            and re.search(r'role\s*=\s*"roles/iam\.workloadIdentityUser"', blk)
            and re.search(rf"member\s*=\s*{re.escape(want_member)}", blk)
        )
        if not ok:
            out.append(f"ERROR OIDC_FEDERATION_OPEN {rel} — {name} must bind {sa} to attribute.environment/{env} only")

    providers = 0
    for tf in sorted(infra.rglob("*.tf*")):
        if ".terraform" in tf.parts:
            continue
        text = tf.read_text()
        code = _code(text) if tf.suffix == ".tf" else text
        r = tf.relative_to(root)
        if re.search(r"\ball(Authenticated)?Users\b", code):
            out.append(f"ERROR OIDC_PUBLIC {r} — a public principal is granted something")
        if "workloadIdentityUser" in code and tf != wif:
            out.append(f"ERROR OIDC_FEDERATION_OPEN {r} — workloadIdentityUser may only be granted in wif.tf")
        if re.search(r"\bprincipalSet?://", code) and tf != wif:
            out.append(f"ERROR OIDC_FEDERATION_OPEN {r} — a federated principal may only be named in wif.tf")
        providers += len(re.findall(r'resource\s+"google_iam_workload_identity_pool(_provider)?"', code))
        if re.search(r'resource\s+"google_service_account_key"|google_service_account_key', code):
            out.append(f"ERROR KEY_FORBIDDEN {r} — no service-account key may exist")
    if providers != 2:  # one pool + one provider
        out.append(f"ERROR OIDC_EXTRA_PROVIDER infra/ — {providers} pool/provider resources, expected exactly 2")
    wf = root / ".github" / "workflows"
    for yml in sorted(wf.glob("*.yml")) if wf.exists() else []:
        if re.search(r"service-accounts\s+keys\s+create", yml.read_text()):
            out.append(f"ERROR KEY_FORBIDDEN {yml.relative_to(root)} — a workflow mints a service-account key")
    return out


def main() -> int:
    found = problems()
    print("\n".join(found))
    if found:
        print(f"FAIL oidc-subjects: {len(found)} blocking finding(s)")
        return 1
    print("ok oidc-subjects: the trust is exactly the expected clauses, applied, exact-match, two doors, no key")
    return 0


if __name__ == "__main__":
    sys.exit(main())
