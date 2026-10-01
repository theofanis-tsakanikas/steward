#!/usr/bin/env python3
"""The shape of the three workflows (project-architecture: ci.yml offline; deploy.yml and destroy.yml gated).

WORKFLOW_TRIGGER        deploy.yml / destroy.yml must be triggered by workflow_dispatch and nothing else
WORKFLOW_NO_ENVIRONMENT a job that authenticates to Google must run in the `deploy` / `destroy` environment
                        (it is what the federation trust names) and may request id-token only there
WORKFLOW_CANCELS_APPLY  no cancel-in-progress on an apply or a destroy (a cancelled apply leaves a lock)
WORKFLOW_KEY            no credentials_json, no secret holding a key: federation only
CI_HAS_CREDENTIALS      ci.yml has no id-token permission and no Google auth step: CI is offline by construction
CI_APPLIES              ci.yml never runs terraform apply or destroy
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
GATED = {"deploy.yml": "deploy", "destroy.yml": "destroy"}


def _on(doc: dict) -> dict:
    return doc.get(True, doc.get("on")) or {}  # PyYAML reads the key `on` as boolean True


def _uses_auth(job: dict) -> bool:
    return any("google-github-actions/auth" in str(s.get("uses", "")) for s in job.get("steps", []))


def problems(root: Path = REPO) -> list[str]:
    out: list[str] = []
    wf = root / ".github" / "workflows"
    for name, env in GATED.items():
        path = wf / name
        rel = path.relative_to(root)
        if not path.exists():
            out.append(f"ERROR WORKFLOW_TRIGGER {rel} — the workflow does not exist")
            continue
        text = path.read_text()
        doc = yaml.safe_load(text)
        triggers = _on(doc)
        if set(triggers) != {"workflow_dispatch"}:
            out.append(
                f"ERROR WORKFLOW_TRIGGER {rel} — triggers are {sorted(triggers)}; only workflow_dispatch may apply"
            )
        if re.search(r"cancel-in-progress:\s*true", text):
            out.append(f"ERROR WORKFLOW_CANCELS_APPLY {rel} — cancel-in-progress must be false")
        if re.search(r"credentials_json|secrets\.[A-Z_]*(KEY|CREDENTIAL|JSON)", text):
            out.append(f"ERROR WORKFLOW_KEY {rel} — a key or credential file is referenced; use federation")
        for jname, job in doc["jobs"].items():
            wants_token = (job.get("permissions") or {}).get("id-token") == "write"
            if (_uses_auth(job) or wants_token) and job.get("environment") != env:
                out.append(
                    f"ERROR WORKFLOW_NO_ENVIRONMENT {rel} — job {jname} authenticates but is not in environment {env!r}"
                )
    ci = wf / "ci.yml"
    if ci.exists():
        text = ci.read_text()
        if "id-token" in text or "google-github-actions/auth" in text:
            out.append(f"ERROR CI_HAS_CREDENTIALS {ci.relative_to(root)} — CI must hold no cloud credentials")
        if re.search(r"terraform\s+(apply|destroy)", text):
            out.append(f"ERROR CI_APPLIES {ci.relative_to(root)} — CI validates; it never applies")
    return out


def main() -> int:
    found = problems()
    print("\n".join(found))
    if found:
        print(f"FAIL workflows: {len(found)} blocking finding(s)")
        return 1
    print("ok workflows: ci is offline; deploy and destroy are dispatch-only, in their environments, keyless")
    return 0


if __name__ == "__main__":
    sys.exit(main())
