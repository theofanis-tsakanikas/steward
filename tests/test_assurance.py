"""The DLP template and the Dataplex scans: derived from the contracts, never wider than the contracts allow."""

from __future__ import annotations

import json

import pytest

from steward import io, pipeline
from steward.core import compile_assurance as ca
from steward.core.contract import DETECTABLE_KINDS

KEY = "infra/assurance/generated.tf.json"


@pytest.fixture(scope="module")
def e():
    return pipeline.load()


@pytest.fixture(scope="module")
def doc(e):
    return e.compiled[KEY]


def test_the_committed_file_is_what_the_contracts_compile_to(doc):
    assert json.loads((io.REPO / KEY).read_text()) == doc


def test_every_detectable_kind_is_asked_for(doc):
    cfg = doc["resource"]["google_data_loss_prevention_inspect_template"]["steward"]["inspect_config"]
    asked = {t["name"] for t in cfg["info_types"]} | {t["info_type"]["name"] for t in cfg["custom_info_types"]}
    assert asked == {ca.DLP_MAP[k][0] for k in DETECTABLE_KINDS}


def test_a_new_detectable_kind_without_a_mapping_stops_the_build(monkeypatch):
    monkeypatch.setattr(ca, "DETECTABLE_KINDS", (*DETECTABLE_KINDS, "passport"))
    with pytest.raises(ValueError, match="passport"):
        ca.inspect_template()


def test_a_finding_never_repeats_the_value(doc):
    assert (
        doc["resource"]["google_data_loss_prevention_inspect_template"]["steward"]["inspect_config"]["include_quote"]
        is False
    )


def test_no_rule_on_a_policy_tagged_column_is_scanned(e, doc):
    tagged = {
        (c.dataset, t, col)
        for c in e.contracts
        for t, tbl in c.tables.items()
        for col, spec in tbl.columns.items()
        if spec.classification.tagged
    }
    assert tagged
    for key, scan in doc["resource"]["google_dataplex_datascan"].items():
        ds, table = scan["labels"]["dataset"], key.removeprefix(f"dq_{scan['labels']['dataset']}_")
        for r in scan["data_quality_spec"]["rules"]:
            assert (ds, table, r["column"]) not in tagged, f"{r['name']} reads a tagged column"


def test_every_scan_over_a_partition_filtered_table_carries_the_filter(doc):
    estate = json.loads((io.REPO / "infra/estate/generated.tf.json").read_text())["resource"]["google_bigquery_table"]
    needing = {k for k, v in estate.items() if v.get("require_partition_filter")}
    carrying = {
        k for k, v in doc["resource"]["google_dataplex_datascan"].items() if "row_filter" in v["data_quality_spec"]
    }
    assert {k.removeprefix("dq_") for k in carrying} == {k.replace("__", "_", 1) for k in needing}


def test_scan_and_rule_names_are_valid_for_dataplex(doc):
    import re

    for scan in doc["resource"]["google_dataplex_datascan"].values():
        assert re.fullmatch(r"[a-z]([a-z0-9-]{0,61}[a-z0-9])?", scan["data_scan_id"])
        names = [r["name"] for r in scan["data_quality_spec"]["rules"]]
        assert len(names) == len(set(names))
        assert all(re.fullmatch(r"[a-zA-Z]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", n) for n in names)


def test_what_a_scan_leaves_out_says_so(doc):
    desc = doc["resource"]["google_dataplex_datascan"]["dq_crm_customers"]["description"]
    assert "Q-CRM-001" in desc and "policy-tagged" in desc


def test_scans_are_on_demand_only(doc):
    for scan in doc["resource"]["google_dataplex_datascan"].values():
        assert scan["execution_spec"] == {"trigger": {"on_demand": {}}}


def _rule(**kw):
    from steward.core.contract import QualityRule

    return QualityRule.model_validate({"id": "Q-XXX-001", **kw})


def test_a_rule_means_what_the_offline_engine_means(e):
    # core/quality.py _check: completeness fails null AND "" ; validity and uniqueness pass a null or empty value;
    # a regex must match the whole value; a bound is exact
    done = ca._rule(_rule(kind="completeness"), "c", "STRING")
    assert done["row_condition_expectation"]["sql_expression"] == "c IS NOT NULL AND c != ''"
    assert "non_null_expectation" in ca._rule(_rule(kind="completeness"), "c", "INTEGER")
    assert ca._rule(_rule(kind="uniqueness"), "c", "STRING")["ignore_null"] is True
    valid = ca._rule(_rule(kind="validity", regex="[A-Z]{2}"), "c", "STRING")
    assert valid["ignore_null"] is True and valid["regex_expectation"]["regex"] == "^(?:[A-Z]{2})$"
    assert ca._rule(_rule(kind="validity", allowed=["A", "B"]), "c", "STRING")["set_expectation"]["values"] == [
        "A",
        "B",
    ]


def test_a_bound_keeps_every_digit():
    assert ca._num(0) == "0" and ca._num(5.0) == "5" and ca._num(1234567.5) == "1234567.5" and ca._num(0.1) == "0.1"
    rng = ca._rule(_rule(kind="validity", min=1234567.5, max=2e7), "c", "FLOAT")["range_expectation"]
    assert rng == {"min_value": "1234567.5", "max_value": "20000000"}


def test_an_unknown_partition_column_type_stops_the_build_instead_of_guessing():
    estate = {
        "resource": {
            "google_bigquery_table": {"d__t": {"require_partition_filter": True, "time_partitioning": {"field": "ts"}}}
        }
    }
    assert ca._partition_filter(estate, "d", "t", {"ts": "TIMESTAMP"}) == "ts >= TIMESTAMP '1970-01-01'"
    assert ca._partition_filter(estate, "d", "t", {"ts": "DATE"}) == "ts >= DATE '1970-01-01'"
    with pytest.raises(ValueError, match="partition column"):
        ca._partition_filter(estate, "d", "t", {})
    with pytest.raises(ValueError, match="partition column"):
        ca._partition_filter(estate, "d", "t", {"ts": "STRING"})


def test_every_scan_runs_as_its_datasets_custodian(e, doc):
    for c in e.contracts:
        for tname in c.tables:
            scan = doc["resource"]["google_dataplex_datascan"].get(f"dq_{c.dataset}_{tname}")
            if scan:
                email = scan["execution_identity"]["service_account"]["email"]
                assert f'var.principals["{c.custodian}"]' in email


def test_a_table_whose_row_policies_leave_the_custodian_out_gets_no_scan(e):
    gov = json.loads(json.dumps(e.compiled["infra/governance/generated.tf.json"]))
    for n in gov["resource"]["google_bigquery_row_access_policy"].values():
        if n["table_id"] == "customers":
            n["grantees"] = [g for g in n["grantees"] if "data-platform" not in g]
    estate = e.compiled["infra/estate/generated.tf.json"]
    with pytest.raises(ValueError, match="custodian"):
        ca.compile_assurance(e.contracts, estate, gov)
