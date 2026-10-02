"""Claims 1 and 5 (live side): the DLP inspect template and the Dataplex data-quality scans, compiled from the
contracts. Nothing here decides anything about the data; it makes GCP look where the contracts say to look.

DLP     the template asks for exactly the kinds the value detector can find (DETECTABLE_KINDS); a kind with no
        mapping stops the build, so a new detectable kind cannot be added to the vocabulary and quietly left
        out of the live scan. Kinds stewards declare from meaning (customer_key, person_name...) cannot be found
        by value and are not asked for.
Dataplex one on-demand scan per table that has rules, run AS THE DATASET'S CUSTODIAN seat (an execution identity).
        The custodian is the one role that sees every row (it loads and deletes them) and no tagged column in
        clear (contracts/_roles.yaml): a scan as any identity outside the row access policies reads zero rows, and
        zero rows pass completeness and uniqueness. So the compiler REFUSES to emit a scan over a table whose row
        policies leave the custodian out. A quality rule is emitted only for a column that is NOT policy-tagged:
        the custodian holds no Fine-Grained Reader, so a rule on a tagged column could only fail with an access
        error. It is left out, and the scan says so (doctrine 1: nothing gets access to personal data by
        default). Left out too: freshness (it needs a clock the synthetic data does not share), referential
        checks and rules on nested columns. The offline engine (claim 5) still judges all.
"""

from __future__ import annotations

import re

from .contract import DETECTABLE_KINDS, Contract, QualityRule
from .sampling import MAX_INSPECT_BYTES, MAX_INSPECT_ROWS, dataplex_sampling_percent, plan_sample

# kind -> (built-in DLP infoType, None) or (custom infoType name, regex)
DLP_MAP: dict[str, tuple[str, str | None]] = {
    "msisdn": ("PHONE_NUMBER", None),
    "imsi": ("STEWARD_IMSI", r"\b[0-9]{15}\b"),  # IMSI and IMEI are both 15 digits: DLP cannot tell them apart by value
    "imei": ("IMEI_HARDWARE_ID", None),
    "email": ("EMAIL_ADDRESS", None),
    "iban": ("IBAN_CODE", None),
    "birth_date": ("DATE_OF_BIRTH", None),
    "address": ("STREET_ADDRESS", None),
}
MAX_FINDINGS_PER_ITEM = 100
MAX_FINDINGS_PER_REQUEST = 1000


def _sorted(d):
    if isinstance(d, dict):
        return {k: _sorted(d[k]) for k in sorted(d)}
    if isinstance(d, list):
        return [_sorted(x) for x in d]
    return d


def inspect_template() -> dict:
    missing = [k for k in DETECTABLE_KINDS if k not in DLP_MAP]
    if missing:
        raise ValueError(f"detectable kinds with no DLP mapping: {missing}")
    builtin = sorted({n for n, rx in DLP_MAP.values() if rx is None})
    custom = [
        {
            "info_type": {"name": name},
            "regex": {"pattern": rx},
            "likelihood": "POSSIBLE",
        }
        for name, rx in sorted(DLP_MAP.values())
        if rx is not None
    ]
    return {
        "steward": {
            "parent": "projects/${var.project_id}/locations/${var.region}",
            "template_id": "steward-inspect",
            "display_name": "steward-inspect",
            "description": "Kinds of personal data the contracts can declare and a value scan can find: "
            + ", ".join(DETECTABLE_KINDS)
            + ". A template cannot limit rows: the sample size belongs to the inspection job (core/sampling.py).",
            "inspect_config": {
                "info_types": [{"name": n} for n in builtin],
                "custom_info_types": custom,
                "min_likelihood": "POSSIBLE",
                "include_quote": False,  # a finding names the column and the kind, never repeats the value
                "limits": {
                    "max_findings_per_item": MAX_FINDINGS_PER_ITEM,
                    "max_findings_per_request": MAX_FINDINGS_PER_REQUEST,
                },
            },
        }
    }


def _num(x: float) -> str:
    """A bound as Terraform wants it, without the rounding of `%g` (1234567.5 must stay 1234567.5)."""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def _rule(r: QualityRule, column: str, col_type: str) -> dict:
    """One contract rule as a Dataplex rule, with the offline engine's semantics (core/quality.py `_check`):
    completeness fails a null AND an empty string (not a blank one); uniqueness and validity pass a null or
    empty value (that is completeness's business) - so `ignore_null`; a regex must match the WHOLE value."""
    base = {"name": r.id.lower(), "column": column, "description": f"Contract rule {r.id} ({r.kind})", "threshold": 1}
    if r.kind == "completeness":
        if col_type == "STRING":
            expr = f"{column} IS NOT NULL AND {column} != ''"
            return {**base, "dimension": "COMPLETENESS", "row_condition_expectation": {"sql_expression": expr}}
        return {**base, "dimension": "COMPLETENESS", "non_null_expectation": {}}
    if r.kind == "uniqueness":
        return {**base, "dimension": "UNIQUENESS", "ignore_null": True, "uniqueness_expectation": {}}
    base["ignore_null"] = True
    if r.allowed is not None:
        return {**base, "dimension": "VALIDITY", "set_expectation": {"values": [str(v) for v in r.allowed]}}
    if r.regex is not None:
        return {**base, "dimension": "VALIDITY", "regex_expectation": {"regex": f"^(?:{r.regex})$"}}
    rng: dict = {}
    if r.min is not None:
        rng["min_value"] = _num(r.min)
    if r.max is not None:
        rng["max_value"] = _num(r.max)
    return {**base, "dimension": "VALIDITY", "range_expectation": rng}


def _partition_filter(estate_doc: dict, dataset: str, table: str, col_type: dict[str, str]) -> str | None:
    """BigQuery refuses a query over a require_partition_filter table without a predicate on the partition
    column; the scan's row_filter is that predicate (a constant lower bound: it keeps every row)."""
    node = estate_doc["resource"]["google_bigquery_table"].get(f"{dataset}__{table}")
    if not node or not node.get("require_partition_filter"):
        return None
    field = node["time_partitioning"]["field"]
    kind = col_type.get(field)
    if kind not in ("DATE", "TIMESTAMP"):  # doctrine 3: no invented type
        raise ValueError(f"{dataset}.{table}: partition column {field!r} has no DATE/TIMESTAMP type in the contract")
    literal = "TIMESTAMP '1970-01-01'" if kind == "TIMESTAMP" else "DATE '1970-01-01'"
    # a constant lower bound, so the predicate is accepted as a partition filter; a row whose partition column is
    # NULL falls outside it (the partition column is a contract-required, non-null field)
    return f"{field} >= {literal}"


def _custodian_sees_every_row(governance_doc: dict, dataset: str, table: str, custodian: str) -> bool:
    """True when the table has no row access policy at all, or the custodian is a grantee of an unfiltered one."""
    policies = [
        n
        for n in governance_doc["resource"].get("google_bigquery_row_access_policy", {}).values()
        if n["dataset_id"] == dataset and n["table_id"] == table
    ]
    ref = f'${{var.principals["{custodian}"]}}'
    return not policies or any(n["filter_predicate"] == "TRUE" and ref in n["grantees"] for n in policies)


def compile_assurance(
    contracts: list[Contract],
    estate_doc: dict,
    governance_doc: dict,
    sizes: dict[str, tuple[int, int]],
) -> dict[str, dict]:
    """`sizes` maps "dataset.table" to (rows, bytes). A scanned table with no size stops the build: how much a scan
    may read is decided from the table's size (core/sampling.py), never assumed (doctrine 3)."""
    scans: dict = {}
    for c in sorted(contracts, key=lambda c: c.dataset):
        for tname, tbl in sorted(c.tables.items()):
            rules, left_out = [], []
            for path, col in tbl.columns.items():
                for r in col.quality:
                    if "." in path:
                        left_out.append(f"{r.id}: nested column {path}")
                    elif col.classification.tagged:
                        left_out.append(f"{r.id}: {path} is policy-tagged")
                    elif r.kind == "referential":
                        left_out.append(f"{r.id}: referential check needs a join the scan cannot make safely")
                    else:
                        rules.append(_rule(r, path, col.type))
            if tbl.freshness:
                left_out.append(f"{tbl.freshness.id}: freshness is judged offline (needs a shared clock)")
            if not rules:
                continue
            if not _custodian_sees_every_row(governance_doc, c.dataset, tname, c.custodian):
                raise ValueError(
                    f"{c.dataset}.{tname}: its row access policies leave the custodian {c.custodian} out; a scan "
                    f"as the custodian would read no rows and pass"
                )
            if f"{c.dataset}.{tname}" not in sizes:
                raise ValueError(f"{c.dataset}.{tname}: no row count and size, so no bound on what its scan may read")
            sample = plan_sample(f"{c.dataset}.{tname}", *sizes[f"{c.dataset}.{tname}"])
            spec: dict = {
                "sampling_percent": dataplex_sampling_percent(sample),
                "rules": sorted(rules, key=lambda x: x["name"]),
            }
            flt = _partition_filter(estate_doc, c.dataset, tname, {p: col.type for p, col in tbl.columns.items()})
            if flt:
                spec["row_filter"] = flt
            ident = re.sub(r"[^a-z0-9]+", "-", f"{c.dataset}-{tname}".lower())
            scans[f"dq_{c.dataset}_{tname}"] = {
                "data_scan_id": f"steward-dq-{ident}",
                "location": "${lower(var.location)}",
                "display_name": f"steward data quality: {c.dataset}.{tname}",
                "description": (
                    f"Rules from the {c.dataset} contract (version {c.version}). On demand; reads at most "
                    f"{MAX_INSPECT_ROWS} rows or {MAX_INSPECT_BYTES // 2**20} MiB of the table."
                    + (f" Not scanned here: {'; '.join(sorted(left_out))}." if left_out else "")
                ),
                "labels": {"dataset": c.dataset, "table": re.sub(r"[^a-z0-9_-]", "-", tname.lower())},
                "data": {
                    "resource": f"//bigquery.googleapis.com/projects/${{var.project_id}}/datasets/{c.dataset}/tables/{tname}"
                },
                "execution_spec": {"trigger": {"on_demand": {}}},
                "execution_identity": {
                    "service_account": {"email": f'${{trimprefix(var.principals["{c.custodian}"], "serviceAccount:")}}'}
                },
                "data_quality_spec": spec,
            }
    doc = {
        "//": "Generated by steward (src/steward/core/compile_assurance.py) from contracts/. Edit the contracts, then `make generate`.",
        "resource": {
            "google_data_loss_prevention_inspect_template": inspect_template(),
            "google_dataplex_datascan": scans,
        },
    }
    return {"infra/assurance/generated.tf.json": _sorted(doc)}
