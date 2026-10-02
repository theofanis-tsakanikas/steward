#!/usr/bin/env python3
"""The deployer's project-IAM power matches what the layers actually hand out.

`roles/resourcemanager.projectIamAdmin` is conditioned (infra/bootstrap/deployer.tf) to grant and revoke only the
roles in `delegable_roles`. Two lists must therefore agree, or the first apply fails on a denial (list too short)
or the deployer keeps a power nothing uses (list too long):

  DEPLOYER_UNDELEGABLE        a layer grants a project role that is not in delegable_roles
  DEPLOYER_DELEGATES_UNUSED   delegable_roles holds a role no layer grants
  DEPLOYER_CONDITION_MISSING  projectIamAdmin is bound without the condition (the deployer could grant itself anything)
  DEPLOYER_BULK_IAM           a layer uses a project-IAM resource the condition does not cover
                              (google_project_iam_binding / _policy / _audit_config)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEPLOYER = "infra/bootstrap/deployer.tf"
BULK = ("google_project_iam_binding", "google_project_iam_policy", "google_project_iam_audit_config")


def layer_roles(root: Path) -> tuple[dict[str, str], list[str]]:
    roles: dict[str, str] = {}
    bulk: list[str] = []
    for layer in sorted((root / "infra").iterdir()):
        if not layer.is_dir() or layer.name == "bootstrap":
            continue
        for f in sorted(layer.glob("*.tf*")):
            text = f.read_text()
            rel = f.relative_to(root)
            for t in BULK:
                if t in text:
                    bulk.append(f"{rel} uses {t}")
            if f.suffix == ".json":
                doc = json.loads(text)
                for node in doc.get("resource", {}).get("google_project_iam_member", {}).values():
                    roles.setdefault(node["role"], str(rel))
            else:
                for block in re.findall(r'resource\s+"google_project_iam_member"[^{]*\{(.*?)\n\}', text, re.S):
                    for r in re.findall(r'role\s*=\s*"([^"]+)"', block):
                        roles.setdefault(r, str(rel))
    return roles, bulk


def problems(root: Path = REPO) -> list[str]:
    out: list[str] = []
    text = (root / DEPLOYER).read_text()
    code = "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())
    m = re.search(r"delegable_roles\s*=\s*\[(.*?)\]", code, re.S)
    delegable = set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()
    granted, bulk = layer_roles(root)
    for r in sorted(set(granted) - delegable):
        out.append(f"ERROR DEPLOYER_UNDELEGABLE {granted[r]} — grants {r}, which the deployer may not delegate")
    for r in sorted(delegable - set(granted)):
        out.append(f"ERROR DEPLOYER_DELEGATES_UNUSED {DEPLOYER} — {r} is delegable but no layer grants it")
    wired = (
        '"roles/resourcemanager.projectIamAdmin" = {' in code
        and "modifiedGrantsByRole" in code
        and "for_each = contains(keys(local.role_conditions), each.value.role)" in re.sub(r"\s+", " ", code)
        and "local.delegable_roles" in code
    )
    if not wired:
        out.append(f"ERROR DEPLOYER_CONDITION_MISSING {DEPLOYER} — projectIamAdmin is not bound with its condition")
    out += [f"ERROR DEPLOYER_BULK_IAM {b}" for b in bulk]
    return out


def main() -> int:
    found = problems()
    print("\n".join(found))
    if found:
        print(f"FAIL deployer-grants: {len(found)} blocking finding(s)")
        return 1
    print("ok deployer-grants: the deployer may delegate exactly the project roles the layers grant")
    return 0


if __name__ == "__main__":
    sys.exit(main())
