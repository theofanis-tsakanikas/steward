#!/usr/bin/env python3
"""Load the synthetic data into the estate and prove the row counts match the generator.

    python scripts/load_synthetic.py --project my-project            # load, then count
    python scripts/load_synthetic.py --project my-project --plan     # print the commands, touch nothing

One `bq load --replace` per table, then the table's row count from its metadata (`bq show`: numRows). A table
whose count differs from its file's line count is a failure: the load is not done until the numbers agree (T011
stop_at). Needs the `bq` CLI and credentials; nothing here runs in CI.

Why metadata and not SELECT COUNT(*): four tables have `require_partition_filter`, which refuses a count with no
predicate; and once governance has applied row access policies the deployer matches none, so a COUNT(*) would
read 0. numRows is neither filtered nor billed - no query is run, so there is nothing to cap.
A re-run loads only the tables whose count is not already right: truncating a table that carries row access
policies is a BigQuery restriction this script does not try to get around.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "synthetic" / "data"
# Tables that exist in the estate because a contract declares them (the `legacy` dataset has none: it is
# the undeclared one, held at the safe state, and is loaded too so the scan has something to find).


def tables() -> list[tuple[str, str, Path]]:
    out = []
    for p in sorted(DATA.glob("*.jsonl")):
        dataset, table = p.stem.split(".", 1)
        out.append((dataset, table, p))
    return out


def load_command(project: str, dataset: str, table: str, path: Path) -> list[str]:
    return [
        "bq",
        f"--project_id={project}",
        "load",
        "--replace",
        "--source_format=NEWLINE_DELIMITED_JSON",
        f"{dataset}.{table}",
        str(path),
    ]


def show_command(project: str, dataset: str, table: str) -> list[str]:
    return ["bq", f"--project_id={project}", "show", "--format=json", f"{project}:{dataset}.{table}"]


def rows_in(show_output: str) -> int | None:
    """numRows from `bq show --format=json`; None when the table is missing or the output cannot be read."""
    try:
        return int(json.loads(show_output)["numRows"])
    except (KeyError, TypeError, ValueError):
        return None


def _rows(project: str, dataset: str, table: str) -> int | None:
    r = subprocess.run(show_command(project, dataset, table), capture_output=True, text=True)
    return rows_in(r.stdout) if r.returncode == 0 else None


def expected(path: Path) -> int:
    return sum(1 for _ in path.open("rb"))


def mismatches(counts: dict[str, int | None], want: dict[str, int]) -> list[str]:
    return [f"{t}: loaded {counts.get(t)}, generator wrote {n}" for t, n in sorted(want.items()) if counts.get(t) != n]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--plan", action="store_true")
    args = ap.parse_args(argv)
    want = {f"{d}.{t}": expected(p) for d, t, p in tables()}
    if args.plan:
        for d, t, p in tables():
            print(" ".join(load_command(args.project, d, t, p)))
            print(" ".join(show_command(args.project, d, t)))
        return 0
    counts: dict[str, int | None] = {}
    for d, t, p in tables():
        if _rows(args.project, d, t) != want[f"{d}.{t}"]:
            subprocess.run(load_command(args.project, d, t, p), check=True)
        counts[f"{d}.{t}"] = _rows(args.project, d, t)
        print(f"{d}.{t}: {counts[f'{d}.{t}']} rows")
    bad = mismatches(counts, want)
    print("\n".join(f"MISMATCH {m}" for m in bad))
    print(f"{'FAIL' if bad else 'ok'} load: {len(counts)} table(s), {sum(v or 0 for v in counts.values())} rows")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
