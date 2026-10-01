"""REAL mode: Collibra's REST API (Import API v2 + Jobs). Used only when a trial instance exists
(DAY-ONE step 7; DECISIONS D2). **Nothing here has run against a real instance** — every call below follows
the developer documentation (docs/COLLIBRA.md, read 2026-10-01) and is marked where it is an assumption.

Configuration (environment, never committed): COLLIBRA_URL, COLLIBRA_USER, COLLIBRA_PASSWORD, and
catalog/collibra.instance.yaml mapping Steward's type/attribute/relation names to the instance's ids and the
contract groups to the instance's user group ids.
"""

from __future__ import annotations

import json
import os
import time

MODE = "REAL"
# The guide lists COMPLETED_WITH_ERROR and ABORTED as outcomes without saying whether they appear as the job
# `state` or the `result`; both are treated as finished and, either way, as not a sync.
FINISHED = {"COMPLETED", "ERROR", "CANCELED", "COMPLETED_WITH_ERROR", "ABORTED", "FAILURE"}


class CollibraClient:
    mode = MODE

    def __init__(self, base_url: str | None = None, user: str | None = None, password: str | None = None):
        import requests  # optional dependency (extra "gcp"); imported only in REAL mode

        self.base = (base_url or os.environ["COLLIBRA_URL"]).rstrip("/")
        self.http = requests.Session()
        self.http.auth = (user or os.environ["COLLIBRA_USER"], password or os.environ["COLLIBRA_PASSWORD"])

    def import_job(self, commands: list[dict], at: str) -> dict:
        """POST {base}/rest/2.0/import/json-job (multipart `file` + form parameters), then poll
        GET {base}/rest/2.0/jobs/{id} (guide: "Job results"). The `/rest/2.0` prefix and the polling field
        names are assumptions to confirm on the trial.

        Parameters are explicit, never left to the instance default: `continueOnError=false` (the default
        before Collibra 2026.07, `true` from it — a partial import must never look like success),
        `relationsAction=REPLACE` and `attributesAction=REPLACE` (what Steward's diff assumes)."""
        r = self.http.post(
            f"{self.base}/rest/2.0/import/json-job",
            files={"file": ("steward.json", json.dumps(commands), "application/json")},
            data={
                "continueOnError": "false",
                "sendNotification": "false",
                "relationsAction": "REPLACE",
                "attributesAction": "REPLACE",
            },
            timeout=60,
        )
        r.raise_for_status()
        job = r.json()
        for _ in range(120):
            resp = self.http.get(f"{self.base}/rest/2.0/jobs/{job['id']}", timeout=30)
            resp.raise_for_status()
            s = resp.json()
            state, result = str(s.get("state", "")).upper(), str(s.get("result", "")).upper()
            if state in FINISHED or result in FINISHED:
                # Only COMPLETED/SUCCESS is a sync. COMPLETED_WITH_ERROR and ABORTED committed part of it.
                if (state, result) != ("COMPLETED", "SUCCESS"):
                    raise RuntimeError(f"Collibra import job {job['id']} ended {state}/{result}: {s.get('message')}")
                return {"mode": self.mode, "commands": len(commands), "job": job["id"], "state": state}
            time.sleep(2)
        raise TimeoutError(f"Collibra import job {job['id']} did not finish")

    def current(self) -> dict[tuple, dict]:
        """Reading the catalog back into command form needs the instance's ids and paging through
        /rest/2.0/assets, /attributes, /relations and /responsibilities; it is written when a trial exists (T024)."""
        raise NotImplementedError("REAL-mode read-back is built in T024, against a trial instance")
