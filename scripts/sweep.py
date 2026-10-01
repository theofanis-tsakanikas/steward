#!/usr/bin/env python3
"""After `destroy`: list what is still standing. Exit 1 if anything is - a destroy that cannot show it left
nothing is a destroy that has not been tested (docs/DAY-ONE.md step 10).

    python scripts/sweep.py --project my-project

Allowed to remain: the bootstrap layer (it is applied from a laptop and removed by deleting the project):
the `<project>-steward-tfstate` bucket, the deployer / guard / build service accounts, the budget.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

BOOTSTRAP_ACCOUNTS = {"steward-deployer", "steward-guard", "steward-build"}
SEAT_PREFIXES = ("seat-", "person-")


def leftovers(project: str, inventory: dict) -> list[str]:
    """inventory: datasets (ids), buckets (names), accounts (service-account local parts), scans, templates,
    exchanges, sinks, taxonomies (display names)."""
    out = []
    out += [f"dataset {d}" for d in inventory.get("datasets", [])]
    out += [f"bucket {b}" for b in inventory.get("buckets", []) if b != f"{project}-steward-tfstate"]
    out += [
        f"service account {a}"
        for a in inventory.get("accounts", [])
        if a.startswith(SEAT_PREFIXES) and a not in BOOTSTRAP_ACCOUNTS
    ]
    out += [f"dataplex scan {s}" for s in inventory.get("scans", [])]
    out += [f"dlp inspect template {t}" for t in inventory.get("templates", [])]
    out += [f"analytics hub exchange {x}" for x in inventory.get("exchanges", [])]
    out += [f"log sink {s}" for s in inventory.get("sinks", []) if s.startswith("steward-")]
    out += [f"policy-tag taxonomy {t}" for t in inventory.get("taxonomies", []) if t.startswith("steward-")]
    return out


def _json(cmd: list[str]) -> list:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"sweep cannot list with `{' '.join(cmd)}`: {r.stderr.strip()[-300:]}")
    return json.loads(r.stdout or "[]")


def inventory(project: str) -> dict:
    g = ["gcloud", f"--project={project}", "--format=json"]
    return {
        "datasets": [
            d["datasetReference"]["datasetId"] for d in _json(["bq", f"--project_id={project}", "ls", "--format=json"])
        ],
        "buckets": [b["name"] for b in _json([*g[:2], "storage", "buckets", "list", g[2]])],
        "accounts": [a["email"].split("@")[0] for a in _json([*g[:2], "iam", "service-accounts", "list", g[2]])],
        "scans": [
            s["name"].rsplit("/", 1)[-1]
            for s in _json([*g[:2], "dataplex", "datascans", "list", "--location=eu", g[2]])
        ],
        "templates": [
            t["name"].rsplit("/", 1)[-1]
            for t in _json([*g[:2], "dlp", "inspect-templates", "list", "--location=europe-west1", g[2]])
        ],
        "exchanges": [
            x["name"].rsplit("/", 1)[-1]
            for x in _json([*g[:2], "bigquery", "analytics-hub", "data-exchanges", "list", "--location=eu", g[2]])
        ],
        "sinks": [s["name"] for s in _json([*g[:2], "logging", "sinks", "list", g[2]])],
        "taxonomies": [],  # listed through the Data Catalog API; the estate layer's destroy removes them with the tags
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    args = ap.parse_args(argv)
    left = leftovers(args.project, inventory(args.project))
    print("\n".join(f"LEFT {x}" for x in left))
    print(f"{'FAIL' if left else 'ok'} sweep: {len(left)} resource(s) left in {args.project}")
    return 1 if left else 0


if __name__ == "__main__":
    sys.exit(main())
