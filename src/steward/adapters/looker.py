"""Looker adapter. LookML is always parsed from files (it is plain text); the Looker API is used only
with a trial (DECISIONS D3, mode REAL). Thin: it turns files into a plain dict and decides nothing.

    {
      "connection": {"name": ..., "runs_as_role": ...},
      "explores": {name: {"from": view, "joins": [view, ...]}},
      "views": {name: {"sql_table_name": "crm.customers", "fields": {name: {kind, type, sql, tags, filters}}}},
      "dashboards": {id: {"title": ..., "elements": [{"name", "explore", "fields": [...]}]}},
    }
"""

from __future__ import annotations

from pathlib import Path

import lkml
import yaml

MODE = "PARSED"  # LookML files; no Looker instance was called


def _fields(view: dict) -> dict:
    out = {}
    for kind in ("dimensions", "measures"):
        for f in view.get(kind, []):
            out[f["name"]] = {
                "kind": kind[:-1],
                "type": f.get("type", "string" if kind == "dimensions" else "count"),
                "sql": f.get("sql"),
                "tags": f.get("tags", []),
                "filters": [next(iter(x.keys())) for group in f.get("filters__all", []) for x in group],
            }
    for g in view.get("dimension_groups", []):
        for tf in g.get("timeframes", ["date"]):
            out[f"{g['name']}_{tf}"] = {
                "kind": "dimension",
                "type": "time",
                "sql": g.get("sql"),
                "tags": [],
                "filters": [],
            }
    return out


def parse(root: Path) -> dict:
    model = {}
    for p in sorted(root.glob("*.model.lkml")):
        model = lkml.load(p.read_text())
    views = {}
    for p in sorted((root / "views").glob("*.view.lkml")):
        for v in lkml.load(p.read_text()).get("views", []):
            table = (v.get("sql_table_name") or "").strip().strip("`")
            views[v["name"]] = {"sql_table_name": table, "fields": _fields(v), "file": str(p.relative_to(root))}
    explores = {
        e["name"]: {"from": e.get("from", e["name"]), "joins": [j["name"] for j in e.get("joins", [])]}
        for e in model.get("explores", [])
    }
    dashboards = {}
    for p in sorted((root / "dashboards").glob("*.dashboard.lookml")):
        for d in yaml.safe_load(p.read_text()):
            dashboards[d["dashboard"]] = {
                "title": d.get("title", d["dashboard"]),
                "elements": [
                    {"name": el["name"], "explore": el.get("explore"), "fields": el.get("fields", [])}
                    for el in d.get("elements", [])
                ],
                "file": str(p.relative_to(root)),
            }
    conn_file = root / "connection.yaml"
    conn = yaml.safe_load(conn_file.read_text()) if conn_file.exists() else {}
    return {
        "mode": MODE,
        "connection": {"name": model.get("connection"), "runs_as_role": conn.get("runs_as_role")},
        "explores": explores,
        "views": views,
        "dashboards": dashboards,
    }
