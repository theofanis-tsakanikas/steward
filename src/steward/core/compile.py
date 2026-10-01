"""Claim 2 (compiled side): contracts → the controls BigQuery enforces, as Terraform JSON.

Pure: contracts + roles + harvest in, {relative path: Terraform JSON document} out. Nothing here knows
a project id or a principal's address — principals are `var.principals["<seat>"]`, bound per
environment, so the same compiled text runs against any project.

What is emitted, and where (each layer has its own state; see docs/adr/0003-layers.md):

  infra/estate/generated.tf.json
    datasets (EU, labels, 48 h time travel) · tables with every tagged leaf carrying its policy tag in
    the schema from the first byte · the classification taxonomy · one policy tag per (classification,
    masking profile) · a `restricted` tag with no readers for every column of a table no contract
    declares (doctrine 1) · a Parameter Manager parameter publishing the policy-tag names
  infra/governance/generated.tf.json
    one data-masking policy per (tag, rule) + Masked Reader per seat · Fine-Grained Reader per seat with
    `clear` · dataset viewer per standing reader seat · row access policies per seat · jobUser per seat

BigQuery masks per policy tag, not per column, so columns that share a classification AND an identical
per-role masking map share one tag. A role absent from a column's masking map gets neither reader
role, so BigQuery refuses the column outright — the safe state.
"""

from __future__ import annotations

import hashlib
import json
import re

from .contract import Classification, Contract, Masking, Roles
from .findings import Finding
from .schema import harvest_columns

GATE = "access"

PREDEFINED = {
    Masking.HASH: "SHA256",
    Masking.NULLIFY: "ALWAYS_NULL",
    Masking.LAST_FOUR: "LAST_FOUR_CHARACTERS",
    Masking.EMAIL_MASK: "EMAIL_MASK",
    Masking.YEAR_ONLY: "DATE_YEAR_MASK",
    Masking.DEFAULT: "DEFAULT_MASKING_VALUE",
}
# Which column types each predefined rule accepts (docs.cloud.google.com/bigquery/docs/column-data-masking-intro,
# read 2026-10-01). A rule on the wrong type is refused at compile time, not at query time.
RULE_TYPES = {
    "SHA256": {"STRING", "BYTES"},
    "LAST_FOUR_CHARACTERS": {"STRING"},
    "EMAIL_MASK": {"STRING"},
    "DATE_YEAR_MASK": {"DATE", "DATETIME", "TIMESTAMP"},
    "ALWAYS_NULL": None,  # any type
    "DEFAULT_MASKING_VALUE": None,
}
MAX_DATA_POLICIES_PER_TAG = 9
CLASS_ABBR = {
    Classification.PERSONAL: "personal",
    Classification.SPECIAL: "special",
    Classification.SENSITIVE_NETWORK: "sensitive_network",
}
RESTRICTED = "restricted"  # the safe-state tag: no reader, no data policy, nobody sees it
TIME_TRAVEL_HOURS = "48"  # the minimum BigQuery allows; shortens how long deleted data stays recoverable
DAY_MS = 86_400_000


def _ident(s: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", s.lower())


def _label(s: str) -> str:
    """GCP label values: lowercase letters, digits, _ and -, at most 63 chars."""
    return re.sub(r"[^a-z0-9_-]", "-", s.lower())[:63]


def _principal_label(p: str) -> str:
    return _label(p.split(":", 1)[1].split("@", 1)[0])


def profile_key(classification: Classification, masking: dict) -> str:
    """The identity of a policy tag: classification + the exact per-role masking map."""
    body = ",".join(f"{r}={masking[r].value}" for r in sorted(masking))
    return f"{CLASS_ABBR[classification]}|{body}"


def _tag_resource(key: str) -> str:
    if key == RESTRICTED:
        return RESTRICTED
    cls, body = key.split("|", 1)
    return f"{cls}_{hashlib.sha256(body.encode()).hexdigest()[:8]}"


def _tag_display(key: str) -> str:
    if key == RESTRICTED:
        return "restricted - no contract - deny all"
    cls, body = key.split("|", 1)
    short = " ".join(f"{r.split('_')[0]}-{m}" for r, m in (x.split("=") for x in body.split(",")))
    return f"{cls} {short}"[:200]


def _schema_fields(fields: list[dict], tag_of: dict[str, str], prefix: str = "") -> list[dict]:
    out = []
    for f in fields:
        path = prefix + f["name"]
        g = {"name": f["name"], "type": f["type"], "mode": f.get("mode", "NULLABLE")}
        if f.get("fields"):
            g["fields"] = _schema_fields(f["fields"], tag_of, path + ".")
        elif path in tag_of:
            g["policyTags"] = {"names": [f"${{google_data_catalog_policy_tag.{_tag_resource(tag_of[path])}.name}}"]}
        out.append(g)
    return out


def check(contracts: list[Contract], roles: Roles) -> list[Finding]:
    """The access gate: ceilings and rule/type fit. Runs before anything is compiled."""
    out: list[Finding] = []
    for c in contracts:
        access = set(c.readers) | set(c.marketplace.grantable_roles) | {"custodian"}
        for fqn, _, _, col in c.iter_columns():
            if not col.classification.tagged:
                continue
            for role, rule in col.masking.items():
                ceiling = roles.ceilings.get(role)
                if rule == Masking.CLEAR:
                    if col.classification == Classification.SPECIAL:
                        out.append(
                            Finding(
                                "ROLE_CEILING_EXCEEDED",
                                GATE,
                                fqn,
                                f"{role} would see special-category data in clear; nobody may",
                            )
                        )
                    elif ceiling is not None:
                        over = sorted(set(col.kinds) - set(ceiling.clear_kinds))
                        if over:
                            out.append(
                                Finding(
                                    "ROLE_CEILING_EXCEEDED",
                                    GATE,
                                    fqn,
                                    f"{role} would see {', '.join(over)} in clear; its ceiling allows clear only for {ceiling.clear_kinds or 'nothing'}",
                                )
                            )
                    continue
                allowed = RULE_TYPES[PREDEFINED[rule]]
                if allowed is not None and col.type not in allowed:
                    out.append(
                        Finding(
                            "MASKING_TYPE_INVALID",
                            GATE,
                            fqn,
                            f"{rule.value} ({PREDEFINED[rule]}) cannot mask a {col.type} column (accepts {sorted(allowed)})",
                        )
                    )
            unreachable = sorted(set(col.masking) - access)
            if unreachable:
                out.append(
                    Finding(
                        "MASKING_ROLE_NO_ACCESS",
                        GATE,
                        fqn,
                        f"masking declared for {unreachable}, who can never read {c.dataset}",
                        severity="warn",
                    )
                )
    tags: dict[str, set[str]] = {}
    for c in contracts:
        for _, _, _, col in c.iter_columns():
            if col.classification.tagged:
                tags.setdefault(profile_key(col.classification, col.masking), set()).update(
                    m.value for m in col.masking.values() if m != Masking.CLEAR
                )
    for key, rules in tags.items():
        if len(rules) > MAX_DATA_POLICIES_PER_TAG:
            out.append(
                Finding(
                    "TOO_MANY_DATA_POLICIES",
                    GATE,
                    key,
                    f"{len(rules)} masking rules on one tag; BigQuery allows {MAX_DATA_POLICIES_PER_TAG}",
                )
            )
    return out


def compile_controls(contracts: list[Contract], roles: Roles, harvest: dict) -> dict[str, dict]:
    estate_cols = harvest_columns(harvest)
    declared = {f"{c.dataset}.{t}": (c, tbl) for c in contracts for t, tbl in c.tables.items()}
    by_dataset = {c.dataset: c for c in contracts}

    # ── policy tags ────────────────────────────────────────────────────────────────────────────
    tag_keys: set[str] = set()
    tag_of_table: dict[str, dict[str, str]] = {}
    for table, cols in estate_cols.items():
        tag_of: dict[str, str] = {}
        if table in declared:
            _, tbl = declared[table]
            for path, col in tbl.columns.items():
                if col.classification.tagged:
                    tag_of[path] = profile_key(col.classification, col.masking)
        else:
            # Doctrine 1: no contract → every leaf column is tagged `restricted`, which no one may read.
            for path, info in cols.items():
                if info.type != "RECORD":
                    tag_of[path] = RESTRICTED
        tag_of_table[table] = tag_of
        tag_keys.update(tag_of.values())

    classes = sorted({k.split("|")[0] for k in tag_keys if k != RESTRICTED})
    estate: dict = {"resource": {}, "locals": {}}
    R = estate["resource"]
    R["google_data_catalog_taxonomy"] = {
        "classification": {
            "display_name": "steward-classification",
            "description": "Generated by steward from contracts/. Do not edit in the console.",
            "region": "${lower(var.location)}",
            "activated_policy_types": ["FINE_GRAINED_ACCESS_CONTROL"],
        }
    }
    pt: dict = {}
    for cls in classes:
        pt[f"class_{cls}"] = {
            "taxonomy": "${google_data_catalog_taxonomy.classification.id}",
            "display_name": cls,
            "description": f"Parent of every {cls} masking profile.",
        }
    for key in sorted(tag_keys):
        res = _tag_resource(key)
        node = {
            "taxonomy": "${google_data_catalog_taxonomy.classification.id}",
            "display_name": _tag_display(key),
            "description": key,
        }
        if key != RESTRICTED:
            node["parent_policy_tag"] = f"${{google_data_catalog_policy_tag.class_{key.split('|')[0]}.id}}"
        else:
            node["description"] = (
                "Safe state (doctrine 1): every column of a table no contract declares. No reader, no masking."
            )
        pt[res] = node
    R["google_data_catalog_policy_tag"] = pt

    # ── datasets and tables ────────────────────────────────────────────────────────────────────
    datasets: dict = {}
    for table in sorted(estate_cols):
        ds = table.split(".")[0]
        if ds in datasets:
            continue
        c = by_dataset.get(ds)
        labels = {"project": "steward", "managed-by": "steward"}
        if c:
            labels |= {
                "owner": _principal_label(c.owner),
                "steward": _principal_label(c.steward),
                "contract-version": str(c.version),
                "retention-days": str(c.retention.period_days),
            }
            desc = f"{c.description} Owner {c.owner}; steward {c.steward}; custodian {c.custodian}."
        else:
            labels |= {"contract": "none"}
            desc = "No contract. Every column is tagged `restricted` and denied to every role (doctrine 1)."
        datasets[ds] = {
            "dataset_id": ds,
            "location": "${var.location}",
            "description": desc,
            "labels": labels,
            "max_time_travel_hours": TIME_TRAVEL_HOURS,
            "delete_contents_on_destroy": True,
        }
    R["google_bigquery_dataset"] = datasets

    tables: dict = {}
    for table in sorted(estate_cols):
        ds, tname = table.split(".")
        spec = harvest[table]
        node: dict = {
            "dataset_id": f"${{google_bigquery_dataset.{ds}.dataset_id}}",
            "table_id": tname,
            "deletion_protection": False,
            "schema": json.dumps(_schema_fields(spec["fields"], tag_of_table[table]), separators=(",", ":")),
            "labels": {"project": "steward", "managed-by": "steward"},
        }
        if table in declared:
            c, tbl = declared[table]
            node["description"] = tbl.description
            node["labels"]["contract-version"] = str(c.version)
        if spec.get("partition"):
            tp = {"type": "DAY", "field": spec["partition"]}
            if table in declared and declared[table][1].retention.mode == "partition":
                c, tbl = declared[table]
                tp["expiration_ms"] = c.table_retention_days(tname) * DAY_MS
            node["time_partitioning"] = tp
            # Cost control: every partitioned table refuses a query that would scan all partitions.
            node["require_partition_filter"] = True
        if spec.get("cluster"):
            node["clustering"] = spec["cluster"]
        tables[_ident(table.replace(".", "__"))] = node
    R["google_bigquery_table"] = tables

    # ── publish policy-tag names for the governance layer (no remote-state reads across layers) ──
    R["google_parameter_manager_parameter"] = {
        "estate": {"parameter_id": "steward-estate", "format": "JSON", "labels": {"project": "steward"}}
    }
    published = {k: f"${{google_data_catalog_policy_tag.{_tag_resource(k)}.name}}" for k in sorted(tag_keys)}
    R["google_parameter_manager_parameter_version"] = {
        "estate": {
            "parameter": "${google_parameter_manager_parameter.estate.id}",
            "parameter_version_id": "${var.publish_version}",
            "parameter_data": "${jsonencode(local.published)}",
        }
    }
    estate["locals"]["published"] = {"policy_tags": published}
    estate["output"] = {"policy_tags": {"value": "${local.published.policy_tags}"}}

    # ── governance ─────────────────────────────────────────────────────────────────────────────
    gov: dict = {"resource": {}, "data": {}, "locals": {}}
    G = gov["resource"]
    gov["data"]["google_parameter_manager_parameter_version"] = {
        "estate": {"parameter": "steward-estate", "parameter_version_id": "${var.estate_version}"}
    }
    seats = [seat for role in sorted(roles.roles) for seat in roles.seats(role)]
    gov["variable"] = {
        "principals": {
            "description": "Seat -> IAM member (user:, group: or serviceAccount:). No default: a seat with no principal is a failed plan, never an invented one (doctrine 3). Seats come from contracts/_roles.yaml.",
            "type": "map(string)",
            "validation": [
                {
                    "condition": "${alltrue([for k in " + json.dumps(seats) + " : contains(keys(var.principals), k)])}",
                    "error_message": "principals must bind every seat in contracts/_roles.yaml: "
                    + ", ".join(seats)
                    + ".",
                },
                {
                    "condition": '${alltrue([for v in values(var.principals) : can(regex("^(user|group|serviceAccount):", v))])}',
                    "error_message": "every principal is user:, group: or serviceAccount:.",
                },
            ],
        }
    }
    gov["locals"]["policy_tags"] = (
        "${jsondecode(data.google_parameter_manager_parameter_version.estate.parameter_data).policy_tags}"
    )

    rules_per_tag: dict[str, dict[str, list[str]]] = {}  # tag key -> rule -> roles
    clear_per_tag: dict[str, list[str]] = {}
    for c in contracts:
        for _, _, _, col in c.iter_columns():
            if not col.classification.tagged:
                continue
            key = profile_key(col.classification, col.masking)
            for role, rule in col.masking.items():
                if rule == Masking.CLEAR:
                    clear_per_tag.setdefault(key, [])
                    if role not in clear_per_tag[key]:
                        clear_per_tag[key].append(role)
                else:
                    lst = rules_per_tag.setdefault(key, {}).setdefault(PREDEFINED[rule], [])
                    if role not in lst:
                        lst.append(role)

    dps, dp_iam, fgr = {}, {}, {}
    for key in sorted(rules_per_tag):
        for rule in sorted(rules_per_tag[key]):
            name = f"{_tag_resource(key)}_{rule.lower()}"
            dps[name] = {
                "location": "${lower(var.location)}",
                "data_policy_id": name,
                "policy_tag": f'${{local.policy_tags["{key}"]}}',
                "data_policy_type": "DATA_MASKING_POLICY",
                "data_masking_policy": {"predefined_expression": rule},
            }
            for role in sorted(rules_per_tag[key][rule]):
                for seat in roles.seats(role):
                    dp_iam[f"{name}__{_ident(seat)}"] = {
                        "project": "${google_bigquery_datapolicy_data_policy." + name + ".project}",
                        "location": "${google_bigquery_datapolicy_data_policy." + name + ".location}",
                        "data_policy_id": "${google_bigquery_datapolicy_data_policy." + name + ".data_policy_id}",
                        "role": "roles/bigquerydatapolicy.maskedReader",
                        "member": f'${{var.principals["{seat}"]}}',
                    }
    for key in sorted(clear_per_tag):
        for role in sorted(clear_per_tag[key]):
            for seat in roles.seats(role):
                fgr[f"{_tag_resource(key)}__{_ident(seat)}"] = {
                    "policy_tag": f'${{local.policy_tags["{key}"]}}',
                    "role": "roles/datacatalog.categoryFineGrainedReader",
                    "member": f'${{var.principals["{seat}"]}}',
                }
    if dps:
        G["google_bigquery_datapolicy_data_policy"] = dps
        G["google_bigquery_datapolicy_data_policy_iam_member"] = dp_iam
    if fgr:
        G["google_data_catalog_policy_tag_iam_member"] = fgr

    viewers, jobusers = {}, {}
    for c in contracts:
        for role in sorted(c.readers):
            for seat in roles.seats(role):
                viewers[f"{c.dataset}__{_ident(seat)}"] = {
                    "dataset_id": c.dataset,
                    "role": "roles/bigquery.dataViewer",
                    "member": f'${{var.principals["{seat}"]}}',
                }
    for role in sorted(roles.roles):
        for seat in roles.seats(role):
            jobusers[_ident(seat)] = {
                "project": "${var.project_id}",
                "role": "roles/bigquery.jobUser",
                "member": f'${{var.principals["{seat}"]}}',
            }
    G["google_bigquery_dataset_iam_member"] = viewers
    G["google_project_iam_member"] = jobusers

    rap = {}
    for c in contracts:
        reach = sorted(set(c.readers) | set(c.marketplace.grantable_roles) | {"custodian"})
        for tname, tbl in c.tables.items():
            col = tbl.row_access.column
            if col is None:
                continue
            unscoped: list[str] = []
            for role in reach:
                r = roles.roles[role]
                if r.scoped_by == col:
                    for scope in r.scopes or []:
                        rap[f"{c.dataset}__{tname}__{_ident(role)}_{scope.lower()}"] = {
                            "dataset_id": c.dataset,
                            "table_id": tname,
                            "policy_id": f"{_ident(role)}_{scope.lower()}",
                            "filter_predicate": f'{col} = "{scope}"',
                            "grantees": [f'${{var.principals["{role}@{scope}"]}}'],
                        }
                else:
                    unscoped.extend(roles.seats(role))
            if unscoped:
                rap[f"{c.dataset}__{tname}__all_rows"] = {
                    "dataset_id": c.dataset,
                    "table_id": tname,
                    "policy_id": "all_rows",
                    "filter_predicate": "TRUE",
                    "grantees": [f'${{var.principals["{s}"]}}' for s in sorted(unscoped)],
                }
    G["google_bigquery_row_access_policy"] = rap

    def _sorted(d):
        if isinstance(d, dict):
            return {k: _sorted(d[k]) for k in sorted(d)}
        if isinstance(d, list):
            return [_sorted(x) for x in d]
        return d

    header = (
        "Generated by steward (src/steward/core/compile.py) from contracts/. Edit the contracts, then `make generate`."
    )
    estate["//"] = header
    gov["//"] = header
    return {"infra/estate/generated.tf.json": _sorted(estate), "infra/governance/generated.tf.json": _sorted(gov)}


def render(docs: dict[str, dict]) -> dict[str, str]:
    return {path: json.dumps(doc, indent=2, ensure_ascii=False) + "\n" for path, doc in docs.items()}


_TAG_REF = re.compile(r"^\$\{google_data_catalog_policy_tag\.([a-z0-9_]+)\.name\}$")


def compiled_column_tags(estate_doc: dict) -> dict[str, str | None]:
    """Read the compiled estate back: {'dataset.table.path': policy-tag resource name or None} for every
    leaf column. This is what claim 1's gate checks — the tag the table will actually carry."""
    out: dict[str, str | None] = {}
    datasets = estate_doc["resource"].get("google_bigquery_dataset", {})

    def walk(fields: list[dict], prefix: str) -> None:
        for f in fields:
            path = prefix + f["name"]
            if f.get("fields"):
                walk(f["fields"], path + ".")
                continue
            names = f.get("policyTags", {}).get("names", [])
            m = _TAG_REF.match(names[0]) if names else None
            out[path] = m.group(1) if m else None

    for node in estate_doc["resource"].get("google_bigquery_table", {}).values():
        ds_ref = re.match(r"^\$\{google_bigquery_dataset\.([a-z0-9_]+)\.dataset_id\}$", node["dataset_id"])
        ds = datasets[ds_ref.group(1)]["dataset_id"] if ds_ref else node["dataset_id"]
        walk(json.loads(node["schema"]), f"{ds}.{node['table_id']}.")
    return out
