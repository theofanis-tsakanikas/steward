#!/usr/bin/env python3
"""After `destroy`: list what is still standing. Exit 1 if anything is - a destroy that cannot show it left
nothing is a destroy that has not been tested (docs/DAY-ONE.md step 10).

    python scripts/sweep.py --project my-project

Allowed to remain: the bootstrap layer (it is applied from a laptop and removed by deleting the project):
the `<project>-steward-tfstate` bucket, Google-managed Cloud Functions buckets named
`gcf-v2-(sources|uploads)-<project-number>-<region>` (guard and reaper), the deployer / destroyer /
guard / reaper / build service accounts, the budget.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request

BOOTSTRAP_ACCOUNTS = {"steward-deployer", "steward-destroyer", "steward-guard", "steward-reaper", "steward-build"}
SEAT_PREFIXES = ("seat-", "person-")
# Google's name for the source/upload buckets it creates when it deploys the bootstrap functions.
GCF_BUCKET = re.compile(r"^gcf-v2-(?:sources|uploads)-\d+-[a-z0-9-]+$")

# Things with no gcloud listing command (checked against gcloud 571: `gcloud dlp inspect-templates` and
# `gcloud bigquery analytics-hub` do not exist) are listed through their REST collection. kind -> (url, key).
REST = {
    "scans": ("https://dataplex.googleapis.com/v1/projects/{p}/locations/europe-west1/dataScans", "dataScans"),
    "templates": (
        "https://dlp.googleapis.com/v2/projects/{p}/locations/europe-west1/inspectTemplates",
        "inspectTemplates",
    ),
    "exchanges": ("https://analyticshub.googleapis.com/v1/projects/{p}/locations/eu/dataExchanges", "dataExchanges"),
    "taxonomies": ("https://datacatalog.googleapis.com/v1/projects/{p}/locations/eu/taxonomies", "taxonomies"),
    "parameters": ("https://parametermanager.googleapis.com/v1/projects/{p}/locations/global/parameters", "parameters"),
    "transfers": (
        "https://bigquerydatatransfer.googleapis.com/v1/projects/{p}/locations/eu/transferConfigs",
        "transferConfigs",
    ),
}
GCLOUD = ("buckets", "accounts", "sinks")
DATASETS = ("datasets",)
KINDS = (*DATASETS, *GCLOUD, *REST)  # every kind the inventory lists; leftovers() must name each one


def leftovers(project: str, inventory: dict) -> list[str]:
    """inventory: kind -> names, for every kind in KINDS."""
    missing = [k for k in KINDS if k not in inventory]
    if missing:
        raise ValueError(f"inventory does not list {missing}: a sweep that does not look is a sweep that passes")
    out = []
    out += [f"dataset {d}" for d in inventory["datasets"]]
    out += [f"bucket {b}" for b in inventory["buckets"] if not _bootstrap_bucket(project, b)]
    out += [
        f"service account {a}"
        for a in inventory["accounts"]
        if a.startswith(SEAT_PREFIXES) and a not in BOOTSTRAP_ACCOUNTS
    ]
    out += [f"dataplex scan {s}" for s in inventory["scans"]]
    out += [f"dlp inspect template {t}" for t in inventory["templates"]]
    out += [f"analytics hub exchange {x}" for x in inventory["exchanges"]]
    out += [f"log sink {s}" for s in inventory["sinks"] if s.startswith("steward-")]
    out += [f"policy-tag taxonomy {t}" for t in inventory["taxonomies"] if t.startswith("steward-")]
    out += [f"parameter {x}" for x in inventory["parameters"] if x.startswith("steward-")]
    out += [f"scheduled query {x}" for x in inventory["transfers"] if x.startswith("steward retention")]
    return out


def _bootstrap_bucket(project: str, name: str) -> bool:
    return name == f"{project}-steward-tfstate" or bool(GCF_BUCKET.fullmatch(name))


def _run(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"sweep cannot list with `{' '.join(cmd)}`: {r.stderr.strip()[-300:]}")
    return r.stdout


def _json(cmd: list[str]) -> list:
    """Parse a gcloud/bq `--format=json` listing. Empty stdout is empty. A notice may precede the
    document; unparseable stdout is an exit, never an empty inventory that looks like a clean sweep."""
    raw = (_run(cmd) or "").strip()
    if not raw:
        return []
    parsed = False
    data = None
    try:
        data = json.loads(raw)
        parsed = True
    except json.JSONDecodeError:
        for i, ch in enumerate(raw):
            if ch not in "[{":
                continue
            try:
                data = json.loads(raw[i:])
                parsed = True
                break
            except json.JSONDecodeError:
                continue
    if not parsed:
        raise SystemExit(f"sweep cannot parse listing from `{' '.join(cmd)}`: {raw[:200]}")
    if data is None:
        return []
    return [data] if isinstance(data, dict) else list(data)


def _rest(url: str, key: str, token: str, project: str) -> list[dict]:
    """Every item of a REST collection, following pages. An error is an exit, never an empty list."""
    items: list[dict] = []
    page = ""
    while True:
        req = urllib.request.Request(
            url + (f"?pageToken={page}" if page else ""),
            headers={"Authorization": f"Bearer {token}", "x-goog-user-project": project},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise SystemExit(f"sweep cannot list {url}: HTTP {e.code}") from e
        items += body.get(key, [])
        page = body.get("nextPageToken", "")
        if not page:
            return items


def _label(kind: str, item: dict) -> str:
    # a taxonomy and a scheduled query are named by what they display, the rest by the last path segment
    if kind in ("taxonomies", "transfers"):
        return item.get("displayName", item["name"])
    return item["name"].rsplit("/", 1)[-1]


def inventory(project: str) -> dict:
    g = ["gcloud", f"--project={project}", "--format=json"]
    inv = {
        "datasets": [
            d["datasetReference"]["datasetId"] for d in _json(["bq", f"--project_id={project}", "ls", "--format=json"])
        ],
        "buckets": [b["name"] for b in _json([*g[:2], "storage", "buckets", "list", g[2]])],
        "accounts": [a["email"].split("@")[0] for a in _json([*g[:2], "iam", "service-accounts", "list", g[2]])],
        "sinks": [s["name"] for s in _json([*g[:2], "logging", "sinks", "list", g[2]])],
    }
    token = _run(["gcloud", "auth", "print-access-token"]).strip()
    for kind, (url, key) in REST.items():
        inv[kind] = [_label(kind, i) for i in _rest(url.format(p=project), key, token, project)]
    return inv


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
