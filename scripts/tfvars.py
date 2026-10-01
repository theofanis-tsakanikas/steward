#!/usr/bin/env python3
"""Write the Terraform variables a layer needs that depend on the project id.

    python scripts/tfvars.py --project my-project --layer governance   > governance.tfvars.json
    python scripts/tfvars.py --project my-project --layer marketplace  > marketplace.tfvars.json

Seats and requesters are stood in for by service accounts that the estate layer creates (infra/seats.json is
generated from the contracts); their addresses follow from the project id alone, so no layer reads another's
state to learn them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEATS = Path(__file__).resolve().parent.parent / "infra" / "seats.json"
PROJECT = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


def member(account: str, project: str) -> str:
    return f"serviceAccount:{account}@{project}.iam.gserviceaccount.com"


def variables(layer: str, project: str, seats: dict) -> dict:
    if not PROJECT.match(project):
        raise ValueError(f"{project!r} is not a GCP project id")
    if layer == "governance":
        return {"principals": {k: member(v, project) for k, v in seats["seats"].items()}}
    if layer == "marketplace":
        return {"grantees": {k: member(v, project) for k, v in seats["people"].items()}}
    raise ValueError(f"layer {layer!r} takes no identity variables")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--layer", required=True, choices=["governance", "marketplace"])
    args = ap.parse_args(argv)
    print(json.dumps(variables(args.layer, args.project, json.loads(SEATS.read_text())), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
