"""The harvested estate schema — what BigQuery's INFORMATION_SCHEMA says exists.

Offline, the harvest is `synthetic/data/_schema.json` (written by the generator, independent of the
contracts). Live, the BigQuery adapter produces the same shape from INFORMATION_SCHEMA.COLUMN_FIELD_PATHS.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldInfo:
    path: str  # e.g. "address.street", "contracts.end_date"
    type: str
    mode: str  # NULLABLE | REQUIRED | REPEATED
    repeated_ancestor: bool  # inside (or is) a REPEATED field


def _norm(t: str) -> str:
    return {"FLOAT64": "FLOAT", "INT64": "INTEGER", "BOOL": "BOOLEAN", "STRUCT": "RECORD"}.get(t, t)


def flatten(fields: list[dict], prefix: str = "", repeated: bool = False) -> list[FieldInfo]:
    out: list[FieldInfo] = []
    for f in fields:
        path = f"{prefix}{f['name']}"
        rep = repeated or f.get("mode") == "REPEATED"
        out.append(FieldInfo(path, _norm(f["type"]), f.get("mode", "NULLABLE"), rep))
        if f.get("fields"):
            out.extend(flatten(f["fields"], path + ".", rep))
    return out


def harvest_columns(harvest: dict) -> dict[str, dict[str, FieldInfo]]:
    """{'crm.customers': {'address.street': FieldInfo, ...}, ...}"""
    return {table: {fi.path: fi for fi in flatten(spec["fields"])} for table, spec in harvest.items()}
