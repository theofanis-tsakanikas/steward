"""Looker adapter. LookML is always parsed from files (it is plain text); the Looker API is used only
with a trial (DECISIONS D3, mode REAL). Thin: it turns files into a plain dict and decides nothing.

Supported: models (one connection each), explores (`from`/`view_name`, joins with `from`), views with
dimensions, measures, dimension groups (time and duration), dashboards (elements' fields, filters, sorts,
dynamic fields; dashboard-level filters). Anything else that changes what a field reads — `extends`,
refinements (`+view`), derived tables — is recorded under `unsupported` so the gate can refuse it rather
than silently mis-read it.
"""

from __future__ import annotations

import re
from pathlib import Path

import lkml
import yaml

MODE = "PARSED"  # LookML files; no Looker instance was called
_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*)\}")


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
        sql = " ".join(x for x in (g.get("sql"), g.get("sql_start"), g.get("sql_end")) if x)
        frames = g.get("timeframes") or g.get("intervals") or ["date"]
        prefix = "s" if g.get("type") == "duration" else ""
        for tf in frames:
            name = f"{tf}{prefix}_{g['name']}" if prefix else f"{g['name']}_{tf}"
            out[name] = {"kind": "dimension", "type": g.get("type", "time"), "sql": sql, "tags": [], "filters": []}
    return out


def _element_refs(el: dict) -> list[str]:
    refs = list(el.get("fields") or [])
    refs += list((el.get("filters") or {}).keys())
    refs += [s.split()[0] for s in (el.get("sorts") or [])]
    for dyn in el.get("dynamic_fields") or []:
        refs += _REF.findall(str(dyn))
    return refs


def parse(root: Path) -> dict:
    conn_file = root / "connection.yaml"
    conn = yaml.safe_load(conn_file.read_text()) if conn_file.exists() else {}
    roles = conn.get("connections", {})
    models, explores, unsupported = {}, {}, []
    for p in sorted(root.glob("*.model.lkml")):
        m = lkml.load(p.read_text())
        name = p.name.removesuffix(".model.lkml")
        models[name] = {"connection": m.get("connection"), "runs_as_role": roles.get(m.get("connection"))}
        for e in m.get("explores", []):
            if "extends" in e or "extends__all" in e or e["name"].startswith("+"):
                unsupported.append(f"explore {e['name']}: extends/refinement")
            explores[e["name"]] = {
                "model": name,
                "from": e.get("from") or e.get("view_name") or e["name"],
                "joins": [j.get("from") or j["name"] for j in e.get("joins", [])],
                "always_join": e.get("always_join", []),
            }
    views = {}
    for p in sorted((root / "views").glob("*.view.lkml")):
        for v in lkml.load(p.read_text()).get("views", []):
            if v["name"].startswith("+") or "extends" in v or "extends__all" in v or "derived_table" in v:
                unsupported.append(f"view {v['name']}: extends, refinement or derived table")
            table = (v.get("sql_table_name") or "").strip().strip("`")
            views[v["name"]] = {"sql_table_name": table, "fields": _fields(v), "file": str(p.relative_to(root))}
    dashboards = {}
    for p in sorted((root / "dashboards").glob("*.dashboard.lookml")):
        for d in yaml.safe_load(p.read_text()):
            dash_filters = [f["field"] for f in d.get("filters", []) or [] if f.get("field")]
            elements = []
            for el in d.get("elements", []):
                if not el.get("explore"):
                    continue  # a text or button tile runs no query
                elements.append(
                    {
                        "name": el["name"],
                        "model": el.get("model"),
                        "explore": el["explore"],
                        "fields": el.get("fields", []),
                        "refs": _element_refs(el),
                    }
                )
            dashboards[d["dashboard"]] = {
                "title": d.get("title", d["dashboard"]),
                "elements": elements,
                "filters": dash_filters,
                "file": str(p.relative_to(root)),
            }
    return {
        "mode": MODE,
        "models": models,
        "explores": explores,
        "views": views,
        "dashboards": dashboards,
        "unsupported": unsupported,
    }
