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
