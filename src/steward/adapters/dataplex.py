"""Claim 5, live: run the on-demand Dataplex data-quality scans the assurance layer declared and keep each result.

The scans, their rules and their execution identity are Terraform (compiled from the contracts); this module only
starts a run of each, waits for it and writes down, per rule, how many rows Dataplex evaluated, passed and found
null. It decides nothing: `evals/dataplex` compares the counts with what the offline quality engine quarantined.
"""

from __future__ import annotations

import time
from collections.abc import Callable

API = "https://dataplex.googleapis.com/v1"
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}


def _int(x) -> int | None:
    return None if x is None else int(x)


def summarize_job(scan_id: str, job: dict) -> dict:
    """One scan job as a plain record. Counts are as Dataplex reports them (int64 arrive as strings)."""
    res = job.get("dataQualityResult") or {}
    rules = []
    for r in res.get("rules", []):
        rule = r.get("rule", {})
        evaluated, passed = _int(r.get("evaluatedCount")), _int(r.get("passedCount"))
        rules.append(
            {
                "rule": rule.get("name", ""),
                "column": rule.get("column", ""),
                "dimension": rule.get("dimension", ""),
                "threshold": rule.get("threshold"),
                "passed": bool(r.get("passed")),
                "evaluated": evaluated,
                "passed_rows": passed,
                "failed_rows": None if evaluated is None or passed is None else evaluated - passed,
                "null_rows": _int(r.get("nullCount")),
            }
        )
    return {
        "scan": scan_id,
        "state": job.get("state"),
        "message": job.get("message", ""),
        "passed": res.get("passed"),
        "rows_scanned": _int(res.get("rowCount")),
        "rules": sorted(rules, key=lambda x: x["rule"]),
    }


def run_scans(
    call: Callable[[str, str, dict | None], dict],
    project: str,
    location: str,
    scan_ids: list[str],
    *,
    timeout: float = 900,
    pause: float = 10,
    sleep=time.sleep,
    clock=time.monotonic,
) -> list[dict]:
    """Start every scan, then poll them all. `call(method, url, body) -> response json`."""
    base = f"{API}/projects/{project}/locations/{location}/dataScans"
    jobs = {}
    for sid in scan_ids:
        jobs[sid] = call("POST", f"{base}/{sid}:run", {})["job"]["name"]
    done: dict[str, dict] = {}
    deadline = clock() + timeout
    while len(done) < len(jobs):
        for sid, name in jobs.items():
            if sid in done:
                continue
            job = call("GET", f"{API}/{name}?view=FULL", None)
            if job.get("state") in TERMINAL:
                done[sid] = job
        if len(done) == len(jobs):
            break
        if clock() > deadline:
            for sid in jobs:
                done.setdefault(sid, {"state": "TIMED_OUT", "message": f"no result within {timeout:.0f}s"})
            break
        sleep(pause)
    return [summarize_job(sid, done[sid]) for sid in scan_ids]
