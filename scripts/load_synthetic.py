#!/usr/bin/env python3
"""Load the synthetic data into the estate and prove the row counts match the generator.

    python scripts/load_synthetic.py --project my-project            # load, then count
    python scripts/load_synthetic.py --project my-project --plan     # print the commands, touch nothing

One `bq load --replace` per table (idempotent), then one COUNT(*) per table with maximum_bytes_billed set
(CLAUDE.md: every query the code runs). A table whose count differs from its file's line count is a failure:
the load is not done until the numbers agree (T011 stop_at). Needs the `bq` CLI and credentials; nothing here
runs in CI.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "synthetic" / "data"
MAX_BYTES = str(10 * 1024 * 1024)  # a COUNT(*) reads no columns; 10 MiB is a ceiling, not an estimate
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


def count_command(project: str, dataset: str, table: str) -> list[str]:
    return [
        "bq",
        f"--project_id={project}",
        "query",
        "--use_legacy_sql=false",
        "--format=json",
        f"--maximum_bytes_billed={MAX_BYTES}",
        f"SELECT COUNT(*) AS n FROM `{project}.{dataset}.{table}`",
    ]


def expected(path: Path) -> int:
    return sum(1 for _ in path.open("rb"))


def mismatches(counts: dict[str, int], want: dict[str, int]) -> list[str]:
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
            print(" ".join(count_command(args.project, d, t)))
        return 0
    counts: dict[str, int] = {}
    for d, t, p in tables():
        subprocess.run(load_command(args.project, d, t, p), check=True)
        r = subprocess.run(count_command(args.project, d, t), check=True, capture_output=True, text=True)
        counts[f"{d}.{t}"] = int(json.loads(r.stdout)[0]["n"])
        print(f"{d}.{t}: {counts[f'{d}.{t}']} rows")
    bad = mismatches(counts, want)
    print("\n".join(f"MISMATCH {m}" for m in bad))
    print(f"{'FAIL' if bad else 'ok'} load: {len(counts)} table(s), {sum(counts.values())} rows")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
