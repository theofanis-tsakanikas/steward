"""Claim 3 — lineage reaches the dashboard, and every dashboard field resolves.

Inputs, all plain data:
  lookml   the parsed LookML project (adapters/looker.py)
  jobs     BigQuery job history: load jobs, table-writing queries, and dashboard queries with the tables
           they referenced. **Offline this is a hand-written fixture**, written after the LookML — clean
           agreement with LookML is therefore constructed, and only the planted drift tests the cross-check.
           Independence needs real Looker query jobs, i.e. a Looker instance (DECISIONS D3, B18).
  catalog  every column the contracts declare (dataset.table.path)
  access   who sees what, from the compiled Terraform (core/simulate.py), per connection role

Blocking findings:
  UNRESOLVED_FIELD                a dashboard reference (field, filter, sort, dynamic field) that is not in
                                  its explore, or whose SQL reaches no catalogued column, or reaches one by a
                                  route the parser cannot verify (raw SQL, a backticked table, an alias.column)
  UNSUPPORTED_LOOKML              extends / refinements / derived tables — refused rather than mis-read
  SENSITIVE_UNMASKED_ON_DASHBOARD a tagged column (any leaf of a RECORD read whole) in clear for the role
  DASHBOARD_FIELD_DENIED          a column the connection's role cannot read at all
  LINEAGE_DISAGREEMENT            tables per LookML ≠ tables the dashboard's recent queries referenced
  LINEAGE_UNMODELLED_DASHBOARD    a dashboard in the job history that LookML does not have
  LINEAGE_UNTRACED                a table a dashboard reads with no path back to a landing source
Reported: LINEAGE_UNOBSERVED, GLOSSARY_CONFLICT, PSEUDONYMISED_ID_ON_DASHBOARD (an enumerable identifier
shown hashed: pseudonymised, still personal data — GDPR Art. 4(5)).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .findings import Finding

GATE = "lineage"
_TABLE_PATH = re.compile(r"\$\{TABLE\}\.([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")
_REF = re.compile(r"\$\{([A-Za-z_]\w*)(?:\.([A-Za-z_]\w*))?\}")
_LIQUID = re.compile(r"\{%.*?%\}|\{\{.*?\}\}", re.S)
_STRING = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_IDENT = re.compile(r"(?<![\w.$`])[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_RAW_SQL = re.compile(r"`|\bFROM\b|\bJOIN\b", re.I)
# FROM that reads no table: EXTRACT(part FROM x) and FROM UNNEST(<a column of this view>)
_HARMLESS_FROM = re.compile(r"\bEXTRACT\s*\(\s*\w+\s+FROM\b|\bFROM\s+UNNEST\s*\(", re.I)
_ALIAS = re.compile(r"\bAS\s+([A-Za-z_]\w*)", re.I)
SQL_WORDS = frozenset(
    {
        "select", "from", "where", "and", "or", "not", "null", "is", "in", "as", "on", "case", "when", "then", "else",
        "end", "exists", "unnest", "distinct", "true", "false", "yes", "no", "interval", "like", "between", "asc", "desc",
        "over", "partition", "by", "order", "limit", "safe", "offset", "ordinal", "struct", "array", "with", "all", "any",
        "string", "int64", "float64", "numeric", "bignumeric", "bool", "bytes", "date", "datetime", "time", "timestamp",
        "year", "quarter", "month", "week", "day", "hour", "minute", "second", "dayofweek", "isoweek", "isoyear",
    }
)  # fmt: skip
_FUNC = re.compile(r"(?<![\w.$`])([A-Za-z_]\w*)\s*\(")
DIRECT_IDENTIFIERS = frozenset({"msisdn", "imsi", "imei", "email", "iban"})
HISTORY_WINDOW_DAYS = 30


@dataclass
class Graph:
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: set[tuple[str, str, str]] = field(default_factory=set)

    def add(self, a: tuple[str, str], b: tuple[str, str], origin: str) -> None:
        for kind, nid in (a, b):
            self.nodes.setdefault(f"{kind}:{nid}", {"kind": kind, "label": nid})
        self.edges.add((f"{a[0]}:{a[1]}", f"{b[0]}:{b[1]}", origin))

    def to_dict(self) -> dict:
        return {
            "nodes": [{"id": k, **v} for k, v in sorted(self.nodes.items())],
            "edges": [{"from": a, "to": b, "origin": o} for a, b, o in sorted(self.edges)],
        }


def resolve(
    views: dict, view: str, fname: str, table_columns: dict[str, set[str]], _seen: frozenset = frozenset()
) -> tuple[set[str], list[str]]:
    """Catalogued columns a LookML field reads, and every reason it could not be verified. Fails closed:
    SQL that reaches nothing the parser can name is an error, never an empty, harmless field."""
    if (view, fname) in _seen:
        return set(), [f"{view}.{fname}: circular reference"]
    v = views.get(view)
    if v is None:
        return set(), [f"view {view!r} does not exist"]
    f = v["fields"].get(fname)
    if f is None:
        return set(), [f"{view}.{fname}: no such field in view {view}"]
    table = v["sql_table_name"]
    known = {c.lower(): c for c in table_columns.get(table, set())}
    cols: set[str] = set()
    bad: list[str] = []
    seen = _seen | {(view, fname)}
    raw_sql = f.get("sql") or ""
    if _LIQUID.search(raw_sql):
        bad.append(
            f"{view}.{fname}: Liquid templating decides at query time what this field reads; not verifiable, refused"
        )
    sql = _LIQUID.sub(" ", raw_sql)
    if re.search(r"\$\{TABLE\}(?!\.)", sql):
        bad.append(f"{view}.{fname}: ${{TABLE}} used as a value reads the whole row; refused")
    for path in _TABLE_PATH.findall(sql):
        cols.add(f"{table}.{known.get(path.lower(), path)}")
    refs = 0
    for a, b in _REF.findall(sql):
        if a == "TABLE":
            continue
        refs += 1
        tv, tf = (a, b) if b else (view, a)
        c, e = resolve(views, tv, tf, table_columns, seen)
        cols |= c
        bad += e
    rest = _STRING.sub(" ", _REF.sub(" ", _TABLE_PATH.sub(" ", sql).replace("${TABLE}", " ")))
    aliases = set(_ALIAS.findall(rest))
    if _RAW_SQL.search(_HARMLESS_FROM.sub(" ", rest)):
        bad.append(f"{view}.{fname}: raw SQL (a subquery or a table reference) reads tables the model does not show")
    functions = {m.lower() for m in _FUNC.findall(rest)}
    for ident in _IDENT.findall(_ALIAS.sub(" ", rest)):
        low = ident.lower()
        if ident.split(".")[0] in aliases:
            continue
        if low in known:
            cols.add(
                f"{table}.{known[low]}"
            )  # a bare column name is valid LookML: Looker selects FROM the view's table
        elif low in SQL_WORDS or low in functions:
            continue
        elif "." in ident:
            bad.append(f"{view}.{fname}: {ident!r} is an alias.column reference the parser cannot tie to a table")
        else:
            bad.append(
                f"{view}.{fname}: {ident!r} is neither a catalogued column of {table} nor SQL the parser knows — refused, not ignored"
            )
    for flt in f.get("filters", []):
        c, e = resolve(views, view, flt, table_columns, seen)
        cols |= c
        bad += e
    if not sql.strip():
        if f["kind"] == "measure" and f["type"] == "count":
            cols.add(f"{table}.*")  # COUNT(*) reads rows, no column
        elif f["kind"] == "dimension":
            if fname in known:
                cols.add(f"{table}.{fname}")
            else:
                bad.append(f"{view}.{fname}: no sql and no column of that name")
    elif not cols and not refs and not bad:
        bad.append(f"{view}.{fname}: its SQL reaches no catalogued column of {table}")
    return cols, bad


def _leaves(col: str, catalog: set[str]) -> list[str]:
    """A RECORD read whole reads every leaf beneath it."""
    kids = [c for c in catalog if c.startswith(col + ".")]
    return [c for c in kids if not any(k.startswith(c + ".") for k in kids)] or [col]


def evaluate(
    lookml: dict,
    jobs: list[dict],
    catalog: set[str],
    tables: set[str],
    access_for,
    kinds_of: dict[str, list[str]],
    captured_at: str,
) -> tuple[list[Finding], Graph, dict]:
    """`access_for(role)(column) -> 'clear' | rule | 'denied…'`, with `.tagged`. `kinds_of[column]` = the
    contract's declared personal-data kinds."""
    out: list[Finding] = []
    g = Graph()
    views, explores = lookml["views"], lookml["explores"]
    table_columns: dict[str, set[str]] = {}
    for c in catalog:
        ds, t, path = c.split(".", 2)
        table_columns.setdefault(f"{ds}.{t}", set()).add(path)
    for u in lookml.get("unsupported", []):
        out.append(
            Finding("UNSUPPORTED_LOOKML", GATE, u.split(":")[0], f"{u} — not parsed, so not verifiable; refused")
        )

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
        reached_views: set[str] = set()
        for el in d["elements"]:
            e = explores.get(el["explore"])
            if e is None:
                out.append(
                    Finding(
                        "UNRESOLVED_FIELD", GATE, f"{did}/{el['name']}", f"explore {el['explore']!r} does not exist"
                    )
                )
                continue
            model = lookml["models"].get(el.get("model") or e["model"], {})
            role = model.get("runs_as_role")
            if not role:
                out.append(
                    Finding(
                        "UNRESOLVED_FIELD",
                        GATE,
                        f"{did}/{el['name']}",
                        f"model {el.get('model') or e['model']!r} has no connection role declared in connection.yaml",
                    )
                )
                continue
            access = access_for(role)
            allowed = {e["from"], *e["joins"]}
            for v in [e["from"], *e.get("always_join", [])]:
                if v in views:
                    lookml_tables[did].add(views[v]["sql_table_name"])  # Looker always selects FROM these
            g.add(("explore", el["explore"]), ("dashboard", did), "lookml")
            refs = list(dict.fromkeys(el["refs"] + [f for f in d.get("filters", []) if f.split(".")[0] in allowed]))
            reached_views.update(allowed)
            for fld in refs:
                view, _, fname = fld.partition(".")
                target = f"{did}/{el['name']}/{fld}"
                if view not in allowed:
                    out.append(
                        Finding(
                            "UNRESOLVED_FIELD", GATE, target, f"view {view!r} is not part of explore {el['explore']!r}"
                        )
                    )
                    continue
                cols, bad = resolve(views, view, fname, table_columns)
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
                    for leaf in _leaves(col, catalog):
                        seen = access(leaf)
                        seen_by_role[leaf] = seen
                        if seen.startswith("denied"):
                            out.append(
                                Finding(
                                    "DASHBOARD_FIELD_DENIED",
                                    GATE,
                                    target,
                                    f"{leaf} is {seen} for {role}: the tile would fail",
                                )
                            )
                        elif seen == "clear" and leaf in access.tagged:
                            out.append(
                                Finding(
                                    "SENSITIVE_UNMASKED_ON_DASHBOARD",
                                    GATE,
                                    target,
                                    f"{leaf} is tagged and reaches the dashboard in clear for {role}",
                                )
                            )
                        elif seen == "SHA256" and set(kinds_of.get(leaf, [])) & DIRECT_IDENTIFIERS:
                            out.append(
                                Finding(
                                    "PSEUDONYMISED_ID_ON_DASHBOARD",
                                    GATE,
                                    target,
                                    f"{leaf} is shown hashed: an unsalted hash of an enumerable identifier is pseudonymised, still personal data (GDPR Art. 4(5)) — fine as a join key, not as a display value",
                                    severity="warn",
                                )
                            )
                rows.append(
                    {
                        "element": el["name"],
                        "field": fld,
                        "columns": sorted(cols),
                        "role": role,
                        "as_seen": seen_by_role,
                    }
                )
        for flt in d.get("filters", []):
            if flt.split(".")[0] not in reached_views:
                out.append(
                    Finding(
                        "UNRESOLVED_FIELD",
                        GATE,
                        f"{did}/filter/{flt}",
                        f"dashboard filter on {flt.split('.')[0]!r}, a view no tile's explore reaches",
                    )
                )
        per_dashboard[did] = rows

    now = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    history: dict[str, set[str]] = {}
    for j in jobs:
        for src in j.get("source_uris", []):
            g.add(("source", src), ("table", j["destination"]), "bigquery-jobs")
        if j.get("destination") and j.get("referenced_tables"):
            for t in j["referenced_tables"]:
                g.add(("table", t), ("table", j["destination"]), "bigquery-jobs")
        dash = (j.get("labels") or {}).get("looker_dashboard")
        if not dash:
            continue
        created = j.get("creation_time")
        when = datetime.fromisoformat(created.replace("Z", "+00:00")) if created else None
        if when is None or when > now:
            why = "has no creation_time" if when is None else f"is dated {created}, after the capture {captured_at}"
            out.append(
                Finding(
                    "LINEAGE_HISTORY_INVALID",
                    GATE,
                    j.get("job_id", "?"),
                    f"dashboard job {why} — history that cannot be placed in time is refused",
                )
            )
            continue
        if now - when <= timedelta(days=HISTORY_WINDOW_DAYS):
            history.setdefault(dash, set()).update(j.get("referenced_tables", []))
    for did in sorted(set(history) - set(lookml["dashboards"])):
        out.append(
            Finding(
                "LINEAGE_UNMODELLED_DASHBOARD",
                GATE,
                did,
                f"queries ran for {did!r} reading {sorted(history[did])}, but no LookML dashboard of that name exists — a user-defined dashboard the catalog cannot describe",
            )
        )
    for did in lookml["dashboards"]:
        if did not in history:
            out.append(
                Finding(
                    "LINEAGE_UNOBSERVED",
                    GATE,
                    did,
                    f"no query in the last {HISTORY_WINDOW_DAYS} days ran for this dashboard — lineage rests on LookML alone",
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
                    f"LookML says {sorted(a)}; its queries referenced {sorted(b)}. Not merged: a hand-written SQL tile, a PDT or a missing view is reading something the model does not show",
                    evidence={"lookml": sorted(a), "history": sorted(b)},
                )
            )

    terms: dict[str, list[tuple[str, str]]] = {}
    for vname, v in views.items():
        for fname, f in v["fields"].items():
            for t in f.get("tags", []):
                if t.startswith("glossary:"):
                    terms.setdefault(t.split(":", 1)[1], []).append(
                        (f"{vname}.{fname}", f"{f['type']}({f.get('sql')}) where {f.get('filters')}")
                    )
    for term, defs in sorted(terms.items()):
        if len({d for _, d in defs}) > 1:
            out.append(
                Finding("GLOSSARY_CONFLICT", GATE, term, "; ".join(f"{w} = {d}" for w, d in defs), severity="warn")
            )

    upstream: dict[str, set[str]] = {}
    for a, b, o in g.edges:
        if o == "bigquery-jobs":
            upstream.setdefault(b, set()).add(a)
    paths = {}
    for did, ts in lookml_tables.items():
        chain = {}
        for t in sorted(ts):
            frontier, seen = {f"table:{t}"}, set()
            while frontier:
                n = frontier.pop()
                seen.add(n)
                frontier |= upstream.get(n, set()) - seen
            chain[t] = sorted(x for x in seen if x != f"table:{t}")
            if not any(x.startswith("source:") for x in chain[t]):
                out.append(
                    Finding(
                        "LINEAGE_UNTRACED",
                        GATE,
                        f"{did}:{t}",
                        f"{t} has no path back to a landing source in the job history",
                    )
                )
        paths[did] = chain
    detail = {
        "dashboards": per_dashboard,
        "paths": paths,
        "lookml_tables": {k: sorted(v) for k, v in lookml_tables.items()},
        "history_tables": {k: sorted(v) for k, v in history.items()},
    }
    return out, g, detail
