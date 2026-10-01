"""The offline loader: source file → rules → destination files. Thin; every decision is core.

    source:       synthetic/data/<table>.jsonl         (counted by lines, before anything parses it)
    destination:  <out>/<table>/loaded.jsonl
                  <out>/<table>/quarantine.jsonl       (rule ids, row key, run id, owner, the row)

Live, the same core runs inside the load job and the destination is BigQuery: `<table>` and
`<table>__quarantine`, whose schema carries the same policy tags as its source (the payload is the
same personal data).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from steward import io
from steward.core.contract import Contract
from steward.core.quality import leaf_values, new_run_id, run


def count_source(table: str) -> int:
    """Newline count of the raw source file — a different reader from the engine's JSON parse."""
    return (io.SYNTHETIC / "data" / f"{table}.jsonl").read_bytes().count(b"\n")


def references(contracts: list[Contract]) -> dict[str, set]:
    refs: dict[str, set] = {}
    for c in contracts:
        for _, _, _, col in c.iter_columns():
            for rule in col.quality:
                if rule.kind == "referential" and rule.references not in refs:
                    ds, t, path = rule.references.split(".", 2)
                    refs[rule.references] = {
                        v for row in io.synthetic_rows(f"{ds}.{t}") for v in leaf_values(row, path) if v is not None
                    }
    return refs


def load_all(contracts: list[Contract], out: Path, today: date, when: datetime | None = None) -> dict:
    when = when or datetime.now(UTC)
    refs = references(contracts)
    summary = {"today": today.isoformat(), "tables": {}}
    for c in contracts:
        for tname in c.tables:
            table = f"{c.dataset}.{tname}"
            source = count_source(table)
            res = run(c, tname, io.synthetic_rows(table), refs, new_run_id(table, when), today)
            d = out / table
            d.mkdir(parents=True, exist_ok=True)
            (d / "loaded.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in res.loaded))
            (d / "quarantine.jsonl").write_text(
                "".join(json.dumps(q.to_dict(with_row=True), sort_keys=True) + "\n" for q in res.quarantined)
            )
            summary["tables"][table] = {
                "run_id": res.run_id,
                "source": source,
                "findings": [f.to_dict() for f in res.findings],
            }
    return summary


def read_destination(out: Path, tables: list[str]) -> tuple[dict, dict]:
    """Count what was written, independently of the engine's in-memory result."""
    counts, quarantine = {}, {}
    for table in tables:
        d = out / table
        loaded = (d / "loaded.jsonl").read_bytes().count(b"\n")
        recs = [json.loads(line) for line in (d / "quarantine.jsonl").read_text().splitlines()]
        counts[table] = {"source": count_source(table), "loaded": loaded, "quarantined": len(recs)}
        quarantine[table] = recs
    return counts, quarantine
