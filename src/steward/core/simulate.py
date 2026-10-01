"""Read the compiled Terraform back and answer: what does this seat see?

This module never reads a contract. It reconstructs access from the generated `.tf.json` alone —
dataset viewers, Fine-Grained Readers, data policies and their Masked Readers, row access policies —
the way BigQuery would evaluate them. evals/access then compares its answers with what the contracts
imply. Two independent readings agreeing is the claim; one function agreeing with itself is not.

It also renders a query's result per seat (`answer`) with the masking rules applied in Python. That
is a **simulation**, labelled as such on every surface; the live transcripts (T012) are the evidence
that BigQuery does the same.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from .compile import compiled_column_tags

_VAR = re.compile(r'^\$\{var\.principals\["([^"]+)"\]\}$')
_LOCAL_TAG = re.compile(r'^\$\{local\.policy_tags\["([^"]+)"\]\}$')
_TAG_NAME = re.compile(r"^\$\{google_data_catalog_policy_tag\.([a-z0-9_]+)\.name\}$")
_DP_REF = re.compile(r"^\$\{google_bigquery_datapolicy_data_policy\.([a-z0-9_]+)\.data_policy_id\}$")


def _seat(member: str) -> str:
    m = _VAR.match(member)
    if not m:
        raise ValueError(f"principal is not a seat variable: {member!r}")
    return m.group(1)


@dataclass
class AccessModel:
    column_tag: dict[str, str | None]  # fqn -> policy-tag resource (or None = untagged)
    viewers: dict[str, set[str]] = field(default_factory=dict)  # dataset -> seats
    fine_grained: dict[str, set[str]] = field(default_factory=dict)  # tag resource -> seats (clear)
    masked: dict[str, dict[str, str]] = field(default_factory=dict)  # tag resource -> seat -> predefined rule
    row_policies: dict[str, list[tuple[str, set[str]]]] = field(
        default_factory=dict
    )  # dataset.table -> [(filter, seats)]


def model(estate: dict, governance: dict) -> AccessModel:
    am = AccessModel(compiled_column_tags(estate))
    key_to_tag = {k: _TAG_NAME.match(v).group(1) for k, v in estate["locals"]["published"]["policy_tags"].items()}
    gr = governance["resource"]
    for node in gr.get("google_bigquery_dataset_iam_member", {}).values():
        if node["role"] == "roles/bigquery.dataViewer":
            am.viewers.setdefault(node["dataset_id"], set()).add(_seat(node["member"]))
    for node in gr.get("google_data_catalog_policy_tag_iam_member", {}).values():
        if node["role"] == "roles/datacatalog.categoryFineGrainedReader":
            tag = key_to_tag[_LOCAL_TAG.match(node["policy_tag"]).group(1)]
            am.fine_grained.setdefault(tag, set()).add(_seat(node["member"]))
    dps = gr.get("google_bigquery_datapolicy_data_policy", {})
    for node in gr.get("google_bigquery_datapolicy_data_policy_iam_member", {}).values():
        if node["role"] != "roles/bigquerydatapolicy.maskedReader":
            continue
        dp = dps[_DP_REF.match(node["data_policy_id"]).group(1)]
        tag = key_to_tag[_LOCAL_TAG.match(dp["policy_tag"]).group(1)]
        rule = dp["data_masking_policy"]["predefined_expression"]
        seat = _seat(node["member"])
        prev = am.masked.setdefault(tag, {}).get(seat)
        if prev and prev != rule:
            raise ValueError(f"{seat} holds two masking rules on {tag}: {prev}, {rule}")
        am.masked[tag][seat] = rule
    for node in gr.get("google_bigquery_row_access_policy", {}).values():
        seats = {_seat(g) for g in node["grantees"]}
        am.row_policies.setdefault(f"{node['dataset_id']}.{node['table_id']}", []).append(
            (node["filter_predicate"], seats)
        )
    return am


DENIED_DATASET = "denied: no dataset access"
DENIED_COLUMN = "denied: policy tag, no reader role"


Grants = frozenset[tuple[str, str]]  # (seat, dataset) pairs holding an approved, unexpired marketplace grant


def effective(am: AccessModel, seat: str, column: str, granted: Grants = frozenset()) -> str:
    """'clear' | a predefined masking rule | a DENIED_* reason. `granted` holds the (seat, dataset)
    pairs with an approved marketplace grant (claim 6) — standing access comes from compiled viewers only."""
    dataset = column.split(".")[0]
    if seat not in am.viewers.get(dataset, set()) and (seat, dataset) not in granted:
        return DENIED_DATASET
    tag = am.column_tag.get(column)
    if tag is None:
        return "clear"
    if seat in am.fine_grained.get(tag, set()):
        return "clear"
    rule = am.masked.get(tag, {}).get(seat)
    return rule or DENIED_COLUMN


def row_filter(am: AccessModel, seat: str, table: str) -> str | None:
    """The predicate rows must satisfy for this seat; None = no rows at all. A table with no row
    access policy shows every row to whoever can read it."""
    policies = am.row_policies.get(table)
    if not policies:
        return "TRUE"
    preds = [f for f, seats in policies if seat in seats]
    if not preds:
        return None
    return "TRUE" if "TRUE" in preds else " OR ".join(sorted(preds))


# ── rendering a query result per seat (simulation) ────────────────────────────────────────────────

_EQ = re.compile(r'^(\w+) = "([^"]*)"$')


def _row_passes(pred: str, row: dict) -> bool:
    if pred == "TRUE":
        return True
    return any((m := _EQ.match(p.strip())) and str(row.get(m.group(1))) == m.group(2) for p in pred.split(" OR "))


def mask(rule: str, value, col_type: str):
    if value is None:
        return None
    if rule == "SHA256":
        return hashlib.sha256(str(value).encode()).hexdigest()
    if rule == "ALWAYS_NULL":
        return None
    if rule == "LAST_FOUR_CHARACTERS":
        s = str(value)
        return s[-4:] if len(s) > 4 else hashlib.sha256(s.encode()).hexdigest()
    if rule == "EMAIL_MASK":
        s = str(value)
        return "XXXXX@" + s.split("@", 1)[1] if "@" in s else hashlib.sha256(s.encode()).hexdigest()
    if rule == "DATE_YEAR_MASK":
        return f"{str(value)[:4]}-01-01"
    if rule == "DEFAULT_MASKING_VALUE":
        return {"STRING": "", "INTEGER": 0, "FLOAT": 0.0, "NUMERIC": 0, "BOOLEAN": False, "DATE": "1970-01-01"}.get(col_type)
    raise ValueError(rule)


def answer(
    am: AccessModel,
    seat: str,
    table: str,
    columns: list[str],
    rows: list[dict],
    types: dict[str, str],
    granted: Grants = frozenset(),
    limit: int = 5,
) -> dict:
    """SELECT <columns> FROM <table> as `seat` would see it. A denied column fails the whole query,
    as BigQuery does (the error lists the columns)."""
    access = {c: effective(am, seat, f"{table}.{c}", granted) for c in columns}
    denied = [c for c, a in access.items() if a.startswith("denied")]
    if any(a == DENIED_DATASET for a in access.values()):
        return {
            "seat": seat,
            "error": f"Access Denied: {seat} has no access to dataset {table.split('.')[0]}",
            "access": access,
        }
    if denied:
        return {
            "seat": seat,
            "error": f"Access Denied: {seat} lacks permission on column(s) {', '.join(denied)} (policy tag)",
            "access": access,
        }
    pred = row_filter(am, seat, table)
    visible = [r for r in rows if pred is not None and _row_passes(pred, r)]
    out_rows = [
        {c: (r.get(c) if access[c] == "clear" else mask(access[c], r.get(c), types[c])) for c in columns}
        for r in visible[:limit]
    ]
    return {
        "seat": seat,
        "row_filter": pred,
        "rows_visible": len(visible),
        "rows_total": len(rows),
        "access": access,
        "rows": out_rows,
    }


def to_json(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=sorted)
