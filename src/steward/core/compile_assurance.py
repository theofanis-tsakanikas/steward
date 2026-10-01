"""Claims 1 and 5 (live side): the DLP inspect template and the Dataplex data-quality scans, compiled from the
contracts. Nothing here decides anything about the data; it makes GCP look where the contracts say to look.

DLP     the template asks for exactly the kinds the value detector can find (DETECTABLE_KINDS); a kind with no
        mapping stops the build, so a new detectable kind cannot be added to the vocabulary and quietly left
        out of the live scan. Kinds stewards declare from meaning (customer_key, person_name...) cannot be found
        by value and are not asked for.
Dataplex one on-demand scan per table that has rules. A quality rule is emitted only for a column that is NOT
        policy-tagged: the scan runs as the Dataplex service agent, which holds no Fine-Grained Reader, so a rule
        on a tagged column could only fail with an access error. It is left out, and the scan says so (doctrine
        1: nothing gets access to personal data by default). Left out too: freshness (it needs a clock the
        synthetic data does not share) and rules on nested columns. The offline engine (claim 5) still judges all.
"""

from __future__ import annotations

import re

from .contract import DETECTABLE_KINDS, Contract, QualityRule

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
            + ". Run on row-limited samples only (CLAUDE.md cost controls).",
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


def _rule(r: QualityRule, column: str, col_type: str) -> dict:
    base = {"name": r.id.lower(), "column": column, "description": f"Contract rule {r.id} ({r.kind})", "threshold": 1}
    if r.kind == "completeness":
        return {**base, "dimension": "COMPLETENESS", "non_null_expectation": {}}
    if r.kind == "uniqueness":
        return {**base, "dimension": "UNIQUENESS", "uniqueness_expectation": {}}
    if r.allowed is not None:
        return {**base, "dimension": "VALIDITY", "set_expectation": {"values": list(r.allowed)}}
    if r.regex is not None:
        return {**base, "dimension": "VALIDITY", "regex_expectation": {"regex": r.regex}}
    rng: dict = {}
    if r.min is not None:
        rng["min_value"] = f"{r.min:g}"
    if r.max is not None:
        rng["max_value"] = f"{r.max:g}"
    return {**base, "dimension": "VALIDITY", "range_expectation": rng}


def _partition_filter(estate_doc: dict, dataset: str, table: str, col_type: dict[str, str]) -> str | None:
    """BigQuery refuses a query over a require_partition_filter table without a predicate on the partition
    column; the scan's row_filter is that predicate (a constant lower bound: it keeps every row)."""
    node = estate_doc["resource"]["google_bigquery_table"].get(f"{dataset}__{table}")
    if not node or not node.get("require_partition_filter"):
        return None
    field = node["time_partitioning"]["field"]
    kind = col_type.get(field, "DATE")
    literal = "TIMESTAMP '1970-01-01'" if kind == "TIMESTAMP" else "DATE '1970-01-01'"
    return f"{field} >= {literal}"


def compile_assurance(contracts: list[Contract], estate_doc: dict) -> dict[str, dict]:
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
            spec: dict = {"sampling_percent": 100, "rules": sorted(rules, key=lambda x: x["name"])}
            flt = _partition_filter(estate_doc, c.dataset, tname, {p: col.type for p, col in tbl.columns.items()})
            if flt:
                spec["row_filter"] = flt
            ident = re.sub(r"[^a-z0-9]+", "-", f"{c.dataset}-{tname}".lower())
            scans[f"dq_{c.dataset}_{tname}"] = {
                "data_scan_id": f"steward-dq-{ident}",
                "location": "${lower(var.location)}",
                "display_name": f"steward data quality: {c.dataset}.{tname}",
                "description": (
                    f"Rules from the {c.dataset} contract (version {c.version}). On demand; small tables only."
                    + (f" Not scanned here: {'; '.join(sorted(left_out))}." if left_out else "")
                ),
                "labels": {"dataset": c.dataset, "table": re.sub(r"[^a-z0-9_-]", "-", tname.lower())},
                "data": {
                    "resource": f"//bigquery.googleapis.com/projects/${{var.project_id}}/datasets/{c.dataset}/tables/{tname}"
                },
                "execution_spec": {"trigger": {"on_demand": {}}},
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
