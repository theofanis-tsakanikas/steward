"""Claim 3 — lineage reaches the dashboard, and every dashboard field resolves.

Inputs, all plain data:
  lookml   the parsed LookML project (adapters/looker.py)
  jobs     BigQuery job history: load jobs, query jobs that write tables, and dashboard queries with the
           tables they actually referenced (`referenced_tables`). Offline a labelled fixture; live,
           INFORMATION_SCHEMA.JOBS. **Independent of LookML** — that is the point.
  catalog  every column the contracts declare (dataset.table.path)
  access   who sees what, from the compiled Terraform (core/simulate.py) — to judge what the Looker
           connection's role actually reads

Gates (blocking):
  UNRESOLVED_FIELD                a dashboard field that is not in its explore's views, or whose SQL
                                  reaches a column no contract declares
  SENSITIVE_UNMASKED_ON_DASHBOARD a tagged column reaching a dashboard in clear for the connection's role
  DASHBOARD_FIELD_DENIED          a field the connection's role cannot read at all (the tile would fail)
  LINEAGE_DISAGREEMENT            the tables LookML says a dashboard reads ≠ the tables its queries
                                  referenced. A disagreement is a finding, never a merge.
Reported (not blocking): LINEAGE_UNOBSERVED (no query history for a dashboard), GLOSSARY_CONFLICT (one
business term, two definitions), the end-to-end path source → table → view → dashboard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .findings import Finding

GATE = "lineage"
_TABLE_COL = re.compile(r"\$\{TABLE\}\.([A-Za-z_][A-Za-z0-9_]*)")
_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:\.([A-Za-z_][A-Za-z0-9_]*))?\}")


@dataclass
class Graph:
    nodes: dict[str, dict] = field(default_factory=dict)  # id -> {kind, label}
    edges: set[tuple[str, str, str]] = field(default_factory=set)  # (from, to, origin)

    def add(self, a: tuple[str, str], b: tuple[str, str], origin: str) -> None:
        for kind, nid in (a, b):
            self.nodes.setdefault(f"{kind}:{nid}", {"kind": kind, "label": nid})
        self.edges.add((f"{a[0]}:{a[1]}", f"{b[0]}:{b[1]}", origin))

    def to_dict(self) -> dict:
        return {
            "nodes": [{"id": k, **v} for k, v in sorted(self.nodes.items())],
            "edges": [{"from": a, "to": b, "origin": o} for a, b, o in sorted(self.edges)],
        }


def resolve(views: dict, view: str, fname: str, _seen: frozenset = frozenset()) -> tuple[set[str], list[str]]:
    """The catalogued columns a LookML field reads, and any reference that does not resolve."""
    if (view, fname) in _seen:
        return set(), [f"{view}.{fname}: circular reference"]
    v = views.get(view)
    if v is None:
        return set(), [f"view {view!r} does not exist"]
    f = v["fields"].get(fname)
    if f is None:
        return set(), [f"{view}.{fname}: no such field in view {view}"]
    cols: set[str] = set()
    bad: list[str] = []
    seen = _seen | {(view, fname)}
    sql = f.get("sql") or ""
    for col in _TABLE_COL.findall(sql):
        cols.add(f"{v['sql_table_name']}.{col}")
    for a, b in _REF.findall(sql.replace("${TABLE}", "")):
        if a == "TABLE":
            continue
        tv, tf = (a, b) if b else (view, a)
        c, e = resolve(views, tv, tf, seen)
        cols |= c
        bad += e
    for flt in f.get("filters", []):
        c, e = resolve(views, view, flt, seen)
        cols |= c
        bad += e
    if not sql and f["kind"] == "measure" and f["type"] == "count":
        cols.add(f"{v['sql_table_name']}.*")  # COUNT(*) reads the table, no column
    return cols, bad


def evaluate(
    lookml: dict, jobs: list[dict], catalog: set[str], tables: set[str], access
) -> tuple[list[Finding], Graph, dict]:
    """`access(column) -> 'clear' | rule | 'denied…'` for the connection's role; `tables` = contracted tables."""
    out: list[Finding] = []
    g = Graph()
    views, explores = lookml["views"], lookml["explores"]
    role = lookml["connection"].get("runs_as_role")

    for name, v in views.items():
        g.add(("table", v["sql_table_name"]), ("view", name), "lookml")
        if v["sql_table_name"] not in tables:
            out.append(
                Finding(
                    "UNRESOLVED_FIELD", GATE, f"view:{name}", f"reads {v['sql_table_name']}, which no contract declares"
                )
            )
    for ename, e in explores.items():
        for v in [e["from"], *e["joins"]]:
            g.add(("view", v), ("explore", ename), "lookml")

    lookml_tables: dict[str, set[str]] = {}
    per_dashboard: dict[str, list[dict]] = {}
    for did, d in lookml["dashboards"].items():
        lookml_tables[did] = set()
        rows = []
        for el in d["elements"]:
            e = explores.get(el["explore"])
            allowed = {e["from"], *e["joins"]} if e else set()
            if e is None:
                out.append(
                    Finding(
                        "UNRESOLVED_FIELD", GATE, f"{did}/{el['name']}", f"explore {el['explore']!r} does not exist"
                    )
                )
            elif e["from"] in views:
                # Looker always selects FROM the explore's base view; joins appear only when a field needs them
                lookml_tables[did].add(views[e["from"]]["sql_table_name"])
            g.add(("explore", el["explore"]), ("dashboard", did), "lookml")
            for fld in el["fields"]:
                view, _, fname = fld.partition(".")
                target = f"{did}/{el['name']}/{fld}"
                if view not in allowed:
                    out.append(
                        Finding(
                            "UNRESOLVED_FIELD", GATE, target, f"view {view!r} is not part of explore {el['explore']!r}"
                        )
                    )
                    continue
                cols, bad = resolve(views, view, fname)
                for b in bad:
                    out.append(Finding("UNRESOLVED_FIELD", GATE, target, b))
                seen_by_role = {}
                for col in sorted(cols):
                    table = col.rsplit(".", 1)[0] if col.endswith(".*") else ".".join(col.split(".")[:2])
                    lookml_tables[did].add(table)
                    if col.endswith(".*"):
                        continue
                    g.add(("column", col), ("dashboard", did), "lookml")
                    if col not in catalog:
                        out.append(
                            Finding(
                                "UNRESOLVED_FIELD",
                                GATE,
                                target,
                                f"reads {col}, which no contract declares — the catalog cannot describe it",
                            )
                        )
                        continue
                    seen = access(col)
                    seen_by_role[col] = seen
                    if seen.startswith("denied"):
                        out.append(
                            Finding(
                                "DASHBOARD_FIELD_DENIED",
                                GATE,
                                target,
                                f"{col} is {seen} for {role}: the tile would fail",
                            )
                        )
                    elif seen == "clear" and col in access.tagged:
                        out.append(
                            Finding(
                                "SENSITIVE_UNMASKED_ON_DASHBOARD",
                                GATE,
                                target,
                                f"{col} is tagged and reaches the dashboard in clear for {role}",
                            )
                        )
                rows.append(
                    {"element": el["name"], "field": fld, "columns": sorted(cols), "as_seen_by": {role: seen_by_role}}
                )
        per_dashboard[did] = rows

    # independent evidence: what the dashboards' queries actually referenced
    history: dict[str, set[str]] = {}
    for j in jobs:
        for src in j.get("source_uris", []):
            g.add(("source", src), ("table", j["destination"]), "bigquery-jobs")
        if j.get("destination") and j.get("referenced_tables"):
            for t in j["referenced_tables"]:
                g.add(("table", t), ("table", j["destination"]), "bigquery-jobs")
        dash = (j.get("labels") or {}).get("looker_dashboard")
        if dash:
            history.setdefault(dash, set()).update(j.get("referenced_tables", []))
    for did in lookml["dashboards"]:
        if did not in history:
            out.append(
                Finding(
                    "LINEAGE_UNOBSERVED",
                    GATE,
                    did,
                    "no query in the job history ran for this dashboard — lineage rests on LookML alone",
                    severity="warn",
                )
            )
            continue
        a, b = lookml_tables[did], history[did]
        if a != b:
            out.append(
                Finding(
                    "LINEAGE_DISAGREEMENT",
                    GATE,
                    did,
                    f"LookML says {sorted(a)}; its queries referenced {sorted(b)}. Not merged: a missing view, a hand-written SQL tile or a PDT is reading something the model does not show",
                    evidence={"lookml": sorted(a), "history": sorted(b)},
                )
            )

    # one business term, one definition
    terms: dict[str, list[tuple[str, str]]] = {}
    for vname, v in views.items():
        for fname, f in v["fields"].items():
            for t in f.get("tags", []):
                if t.startswith("glossary:"):
                    definition = f"{f['type']}({f.get('sql')}) where {f.get('filters')}"
                    terms.setdefault(t.split(":", 1)[1], []).append((f"{vname}.{fname}", definition))
    for term, defs in sorted(terms.items()):
        if len({d for _, d in defs}) > 1:
            out.append(
                Finding("GLOSSARY_CONFLICT", GATE, term, "; ".join(f"{w} = {d}" for w, d in defs), severity="warn")
            )

    paths = {}
    upstream = {}
    for a, b, o in g.edges:
        if o == "bigquery-jobs":
            upstream.setdefault(b, set()).add(a)
    for did, ts in lookml_tables.items():
        chain = {}
        for t in sorted(ts):
            frontier, seen = {f"table:{t}"}, set()
            while frontier:
                n = frontier.pop()
                seen.add(n)
                frontier |= upstream.get(n, set()) - seen
            chain[t] = sorted(x for x in seen if x != f"table:{t}")
        paths[did] = chain
    return (
        out,
        g,
        {
            "dashboards": per_dashboard,
            "paths": paths,
            "lookml_tables": {k: sorted(v) for k, v in lookml_tables.items()},
            "history_tables": {k: sorted(v) for k, v in history.items()},
        },
    )
