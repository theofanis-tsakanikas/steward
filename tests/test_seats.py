"""Seat identities: derived from the contracts, collision-free, and consistent with the governance variable."""

from __future__ import annotations

import importlib.util
import json
import re

import pytest

from steward import io, pipeline
from steward.core.compile_seats import account_id, compile_seats, contract_seats

spec = importlib.util.spec_from_file_location("tfvars", io.REPO / "scripts" / "tfvars.py")
tfvars = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tfvars)


@pytest.fixture(scope="module")
def e():
    return pipeline.load()


def test_account_ids_follow_the_seat():
    assert account_id("analyst@GR") == "seat-analyst-gr"
    assert account_id("bi_service") == "seat-bi-service"
    assert account_id("group:crm-stewards@halverra.example") == "seat-crm-stewards"
    assert account_id("user:eleni.kosta@halverra.example") == "person-eleni-kosta"


def test_an_id_gcp_would_refuse_is_an_error_not_a_truncation():
    with pytest.raises(ValueError):
        account_id("group:" + "x" * 40 + "@halverra.example")
    with pytest.raises(ValueError):
        account_id("--")


def test_every_governance_seat_has_an_identity(e):
    doc = json.loads((io.REPO / "infra" / "seats.json").read_text())
    gov = e.compiled["infra/governance/generated.tf.json"]["variable"]["principals"]["validation"][0]["condition"]
    required = set(json.loads(re.search(r"for k in (\[.*?\]) :", gov).group(1)))
    assert required == set(doc["seats"]) == set(contract_seats(e.contracts, e.roles))


def test_tfvars_satisfy_the_generated_validation(e):
    seats = json.loads((io.REPO / "infra" / "seats.json").read_text())
    principals = tfvars.variables("governance", "steward-demo-1", seats)["principals"]
    assert all(re.match(r"^(user|group|serviceAccount):", v) for v in principals.values())
    custodians = {c.custodian for c in e.contracts}
    assert custodians and all(principals[c].startswith("serviceAccount:") for c in custodians)
    grantees = tfvars.variables("marketplace", "steward-demo-1", seats)["grantees"]
    assert grantees  # the people holding a live grant (the next test ties them to the compiled IAM)
    assert all(v.startswith("serviceAccount:") for v in grantees.values())


def test_a_grantee_exists_for_everyone_holding_a_live_grant(e):
    node = e.compiled["infra/marketplace/generated.tf.json"]["resource"]["google_bigquery_dataset_iam_member"]
    members = {
        re.search(r'var\.grantees\["(.+?)"\]', n["member"]).group(1) for n in node.values() if "grantees" in n["member"]
    }
    assert members and members <= set(json.loads((io.REPO / "infra" / "seats.json").read_text())["people"])


def test_the_resources_are_generated_from_the_same_mapping(e):
    mapping = json.loads((io.REPO / "infra" / "seats.json").read_text())
    ids = {*mapping["seats"].values(), *mapping["people"].values()}
    accounts = e.compiled["infra/estate/identities.tf.json"]["resource"]["google_service_account"]
    assert {a["account_id"] for a in accounts.values()} == ids


def test_two_seats_that_share_an_id_are_refused(e):
    from steward.core.contract import Roles

    doc = io.roles_doc()
    doc["roles"]["analyst"]["scopes"] = ["GR", "G.R"]
    with pytest.raises(ValueError):
        compile_seats(e.contracts, Roles.model_validate(doc), [])


def test_tfvars_refuses_a_malformed_project_and_an_unknown_layer():
    with pytest.raises(ValueError):
        tfvars.variables("governance", "Not A Project", {"seats": {}, "people": {}})
    with pytest.raises(ValueError):
        tfvars.variables("estate", "steward-demo-1", {"seats": {}, "people": {}})
