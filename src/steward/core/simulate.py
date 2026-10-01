"""Read the compiled Terraform back and answer: what does this seat see?

This module never reads a contract. It reconstructs access from the generated `.tf.json` alone —
dataset viewers, Fine-Grained Readers, data policies and their Masked Readers, row access policies —
for the **modelled IAM subset**, and it refuses to model anything outside that subset: an IAM resource,
role or condition not on the allowlist below raises `Unmodelled` rather than being ignored, so an
additive grant (a project-level Fine-Grained Reader, a dataOwner) cannot slip past as "not modelled".
evals/access compares its answers with what the contracts imply.

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


class Unmodelled(ValueError):
    """The compiled Terraform contains access this simulator cannot evaluate. Refused, never ignored."""


# resource type -> allowed IAM roles (None = not an IAM resource; must carry no member/role)
ALLOWED = {
    "google_data_catalog_taxonomy": None,
    "google_data_catalog_policy_tag": None,
    "google_bigquery_dataset": None,
    "google_bigquery_table": None,
    "google_parameter_manager_parameter": None,
    "google_parameter_manager_parameter_version": None,
    "google_bigquery_datapolicy_data_policy": None,
    "google_bigquery_row_access_policy": None,
    "google_storage_bucket": None,
    "google_bigquery_data_transfer_config": None,  # runs as the custodian (B12); grants nothing
    "google_bigquery_datapolicy_data_policy_iam_member": {"roles/bigquerydatapolicy.maskedReader"},
    "google_data_catalog_policy_tag_iam_member": {"roles/datacatalog.categoryFineGrainedReader"},
    "google_bigquery_dataset_iam_member": {"roles/bigquery.dataViewer", "roles/bigquery.dataEditor"},
    "google_project_iam_member": {"roles/bigquery.jobUser", "roles/iam.serviceAccountShortTermTokenMinter"},
}

# A role that is modelled only for one kind of member. The token minter lets the BigQuery Data Transfer service
# agent run the scheduled retention queries as the custodian; it reads nothing and gives no seat anything. Granted
# to any other member it would be an unmodelled path to impersonation, so it is refused.
_ONLY_FOR = {
    "roles/iam.serviceAccountShortTermTokenMinter": re.compile(
        r"^serviceAccount:service-\$\{data\.google_project\.this\.number\}@gcp-sa-bigquerydatatransfer\.iam\.gserviceaccount\.com$"
    )
}


ESTATE_TYPES = frozenset(k for k, v in ALLOWED.items() if v is None) - {
    "google_bigquery_datapolicy_data_policy",
    "google_bigquery_row_access_policy",
}
TOP_LEVEL = frozenset({"//", "resource", "data", "locals", "variable", "output"})
_IAM_KEYS = frozenset(
    {"access", "role", "member", "members", "grantees", "condition", "iam", "policy_data", "bindings"}
)


def _iam_keys_anywhere(node, path: str = "") -> list[str]:
    """Every IAM-shaped key at any depth — an inline `access {}` block grants as surely as a resource does."""
    found = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _IAM_KEYS:
                found.append(f"{path}.{k}" if path else k)
            found += _iam_keys_anywhere(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += _iam_keys_anywhere(v, f"{path}[{i}]")
    return found


# Keys that look like IAM but are not, by exact (resource type, path pattern). Narrow on purpose.
_NOT_IAM = [
    ("google_bigquery_row_access_policy", re.compile(r"^grantees$")),  # modelled: read into row_policies
    ("google_storage_bucket", re.compile(r"^lifecycle_rule\[\d+\]\.condition$")),  # an object-age rule
]


def _allowlisted(doc: dict, layer: str) -> None:
    unknown_top = sorted(set(doc) - TOP_LEVEL)
    if unknown_top:
        raise Unmodelled(f"{layer}: top-level blocks {unknown_top} are not modelled")
    for rtype, nodes in doc.get("resource", {}).items():
        allowed_types = ESTATE_TYPES if layer == "estate" else set(ALLOWED)
        if rtype not in allowed_types:
            raise Unmodelled(f"{layer}: resource type {rtype} is not modelled in this layer")
        roles = ALLOWED[rtype]
        for name, node in nodes.items():
            where = f"{rtype}.{name}"
            if roles is None:
                stray = [
                    k for k in _iam_keys_anywhere(node) if not any(rtype == t and rx.match(k) for t, rx in _NOT_IAM)
                ]
                if stray:
                    raise Unmodelled(f"{where} carries IAM the model does not read: {stray}")
                continue
            extra = set(node) - {"role", "member", "project", "location", "data_policy_id", "dataset_id", "policy_tag"}
            if extra:
                raise Unmodelled(f"{where}: keys {sorted(extra)} are not modelled")
            if node.get("role") not in roles:
                raise Unmodelled(f"{where}: role {node.get('role')} is not modelled")
            only = _ONLY_FOR.get(node.get("role"))
            if only and not only.match(str(node.get("member", ""))):
                raise Unmodelled(
                    f"{where}: role {node.get('role')} is modelled only for the Data Transfer service agent"
                )
            if only:
                continue
            if not _VAR.match(str(node.get("member", ""))):
                raise Unmodelled(f"{where}: member {node.get('member')!r} is not a seat variable")


def _seat(member: str) -> str:
    m = _VAR.match(member)
    if not m:
        raise Unmodelled(f"principal is not a seat variable: {member!r}")
    return m.group(1)


@dataclass
class AccessModel:
    column_tag: dict[str, str | None]  # fqn -> policy-tag resource (or None = untagged)
    viewers: dict[str, set[str]] = field(default_factory=dict)  # dataset -> seats (dataViewer)
    editors: dict[str, set[str]] = field(default_factory=dict)  # dataset -> seats (dataEditor: write, and read)
    fine_grained: dict[str, set[str]] = field(default_factory=dict)  # tag resource -> seats (clear)
    masked: dict[str, dict[str, str]] = field(default_factory=dict)  # tag resource -> seat -> predefined rule
    row_policies: dict[str, list[tuple[str, set[str]]]] = field(
        default_factory=dict
    )  # dataset.table -> [(filter, seats)]


def model(estate: dict, governance: dict) -> AccessModel:
    _allowlisted(estate, "estate")
    _allowlisted(governance, "governance")
    am = AccessModel(compiled_column_tags(estate))
    key_to_tag = {k: _TAG_NAME.match(v).group(1) for k, v in estate["locals"]["published"]["policy_tags"].items()}
    gr = governance["resource"]
    for node in gr.get("google_bigquery_dataset_iam_member", {}).values():
        target = am.viewers if node["role"] == "roles/bigquery.dataViewer" else am.editors
        target.setdefault(node["dataset_id"], set()).add(_seat(node["member"]))
    for name, node in gr.get("google_data_catalog_policy_tag_iam_member", {}).items():
        if node["role"] == "roles/datacatalog.categoryFineGrainedReader":
            tag = _tag_of(key_to_tag, node["policy_tag"], name)
            am.fine_grained.setdefault(tag, set()).add(_seat(node["member"]))
    dps = gr.get("google_bigquery_datapolicy_data_policy", {})
    for node in gr.get("google_bigquery_datapolicy_data_policy_iam_member", {}).values():
        if node["role"] != "roles/bigquerydatapolicy.maskedReader":
            continue
        ref = _DP_REF.match(node["data_policy_id"])
        if not ref or ref.group(1) not in dps:
            raise Unmodelled(f"masked reader on an unknown data policy: {node['data_policy_id']}")
        dp = dps[ref.group(1)]
        tag = _tag_of(key_to_tag, dp["policy_tag"], ref.group(1))
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


def _tag_of(key_to_tag: dict, ref: str, where: str) -> str:
    """Grants are modelled on published leaf tags only. A grant on a parent (class) tag, which would
    reach every child, or on anything else, is refused as unmodelled."""
    m = _LOCAL_TAG.match(ref)
    if not m or m.group(1) not in key_to_tag:
        raise Unmodelled(f"{where}: grant on {ref!r}, which is not a published leaf policy tag")
    return key_to_tag[m.group(1)]


DENIED_DATASET = "denied: no dataset access"
DENIED_COLUMN = "denied: policy tag, no reader role"


Grants = frozenset[tuple[str, str]]  # (seat, dataset) pairs holding an approved, unexpired marketplace grant


def effective(am: AccessModel, seat: str, column: str, granted: Grants = frozenset()) -> str:
    """'clear' | a predefined masking rule | a DENIED_* reason. `granted` holds the (seat, dataset)
    pairs with an approved marketplace grant (claim 6) — standing access comes from compiled viewers only."""
    dataset = column.split(".")[0]
    readers = am.viewers.get(dataset, set()) | am.editors.get(dataset, set())
    if seat not in readers and (seat, dataset) not in granted:
        return DENIED_DATASET
    tag = am.column_tag.get(column)
    if tag is None:
        return "clear"
    return tag_grant(am, seat, tag) or DENIED_COLUMN


def tag_grant(am: AccessModel, seat: str, tag: str) -> str | None:
    """What a seat holds on a policy tag, independent of any dataset access: 'clear' (Fine-Grained
    Reader wins over masking), a masking rule, or None."""
    if seat in am.fine_grained.get(tag, set()):
        return "clear"
    return am.masked.get(tag, {}).get(seat)


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


def _b64sha(value) -> str:
    import base64

    return base64.b64encode(hashlib.sha256(str(value).encode()).digest()).decode()


def mask(rule: str, value, col_type: str):
    if value is None:
        return None
    # Output shapes per the BigQuery masking docs (read 2026-10-01). The SHA-256 rendering (base64 of
    # the digest) is this simulator's; live transcripts (T012) are compared by rule, not by value.
    if rule == "SHA256":
        return _b64sha(value)
    if rule == "ALWAYS_NULL":
        return None
    if rule == "LAST_FOUR_CHARACTERS":
        s = str(value)
        return "XXXXX" + s[-4:] if len(s) > 4 else _b64sha(s)
    if rule == "EMAIL_MASK":
        s = str(value)
        return "XXXXX@" + s.split("@", 1)[1] if "@" in s else _b64sha(s)
    if rule == "DATE_YEAR_MASK":
        return f"{str(value)[:4]}-01-01"
    if rule == "DEFAULT_MASKING_VALUE":
        return {"STRING": "", "INTEGER": 0, "FLOAT": 0.0, "NUMERIC": 0, "BOOLEAN": False, "DATE": "1970-01-01"}.get(
            col_type
        )
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
