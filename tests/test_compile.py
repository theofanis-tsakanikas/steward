import copy

import pytest

from steward import io, pipeline
from steward.core.compile import RESTRICTED, check
from steward.core.simulate import DENIED_COLUMN, DENIED_DATASET, effective, model


def gate(docs=None, roles=None):
    e = pipeline.load(contract_docs=docs, roles_doc=roles)
    return {(f.code, f.target) for f in check(e.contracts, e.roles) if f.blocking}


def test_committed_contracts_pass_the_access_gate():
    assert gate() == set()


def test_analyst_in_clear_on_msisdn_is_refused():
    docs = copy.deepcopy(io.contract_docs())
    docs["crm"]["tables"]["customers"]["columns"]["msisdn"]["masking"]["analyst"] = "clear"
    assert gate(docs) == {("ROLE_CEILING_EXCEEDED", "crm.customers.msisdn")}


def test_fraud_in_clear_on_free_text_is_refused():
    docs = copy.deepcopy(io.contract_docs())
    docs["crm"]["tables"]["support_tickets"]["columns"]["notes_free_text"]["masking"]["fraud_investigator"] = "clear"
    assert gate(docs) == {("ROLE_CEILING_EXCEEDED", "crm.support_tickets.notes_free_text")}


def test_special_category_is_never_clear():
    docs = copy.deepcopy(io.contract_docs())
    col = docs["crm"]["tables"]["customers"]["columns"]["msisdn"]
    col["classification"] = "special"
    assert ("ROLE_CEILING_EXCEEDED", "crm.customers.msisdn") in gate(docs)


@pytest.mark.parametrize("column,rule", [("birth_date", "hash"), ("msisdn", "year_only"), ("birth_date", "last_four")])
def test_masking_rule_must_fit_the_type(column, rule):
    docs = copy.deepcopy(io.contract_docs())
    docs["crm"]["tables"]["customers"]["columns"][column]["masking"]["steward"] = rule
    assert ("MASKING_TYPE_INVALID", f"crm.customers.{column}") in gate(docs)


def test_raising_a_ceiling_is_visible_in_roles_not_in_a_contract():
    roles = copy.deepcopy(io.roles_doc())
    roles["ceilings"]["analyst"]["clear_kinds"] = ["msisdn"]
    docs = copy.deepcopy(io.contract_docs())
    docs["crm"]["tables"]["customers"]["columns"]["msisdn"]["masking"]["analyst"] = "clear"
    assert gate(docs, roles) == set()


def test_uncontracted_columns_are_restricted_and_restricted_has_no_reader():
    e = pipeline.load()
    tags = e.compiled_tags
    legacy = [c for c in tags if c.startswith("legacy.")]
    assert legacy and all(tags[c] == RESTRICTED for c in legacy)
    gov = e.compiled["infra/governance/generated.tf.json"]["resource"]
    text = str(gov)
    assert '"restricted"' not in text and 'policy_tags["restricted"]' not in text


def test_role_absent_from_masking_gets_no_reader_role():
    docs = copy.deepcopy(io.contract_docs())
    del docs["crm"]["tables"]["customers"]["columns"]["email"]["masking"]["steward"]
    e = pipeline.load(contract_docs=docs)
    am = model(e.compiled["infra/estate/generated.tf.json"], e.compiled["infra/governance/generated.tf.json"])
    steward = "group:crm-stewards@halverra.example"
    assert effective(am, steward, "crm.customers.email") == DENIED_COLUMN
    assert effective(am, steward, "crm.customers.msisdn") == "LAST_FOUR_CHARACTERS"


def test_a_dataset_steward_governs_only_its_dataset():
    e = pipeline.load()
    am = model(e.compiled["infra/estate/generated.tf.json"], e.compiled["infra/governance/generated.tf.json"])
    assert effective(am, "group:finance-stewards@halverra.example", "crm.customers.msisdn") == DENIED_DATASET
    assert effective(am, "group:finance-stewards@halverra.example", "finance.billing.iban") == "LAST_FOUR_CHARACTERS"


def test_custodian_writes_but_never_reads_a_tag_in_clear():
    e = pipeline.load()
    am = model(e.compiled["infra/estate/generated.tf.json"], e.compiled["infra/governance/generated.tf.json"])
    custodian = "group:data-platform@halverra.example"
    assert all(custodian not in seats for seats in am.fine_grained.values())
    assert custodian in am.editors["crm"]
    assert effective(am, custodian, "crm.customers.msisdn") == DENIED_COLUMN


def test_undeclared_column_of_a_declared_table_compiles_restricted():
    harvest = copy.deepcopy(io.harvest())
    harvest["crm.customers"]["fields"].append({"name": "alt_phone", "type": "STRING", "mode": "NULLABLE"})
    assert pipeline.load(harvest=harvest).compiled_tags["crm.customers.alt_phone"] == RESTRICTED


def test_unmodelled_iam_is_refused():
    from steward.core.simulate import Unmodelled

    e = pipeline.load()
    gov = copy.deepcopy(e.compiled["infra/governance/generated.tf.json"])
    gov["resource"]["google_project_iam_member"]["x"] = {
        "project": "p",
        "role": "roles/bigquery.dataOwner",
        "member": '${var.principals["analyst@GR"]}',
    }
    with pytest.raises(Unmodelled):
        model(e.compiled["infra/estate/generated.tf.json"], gov)


def test_the_token_minter_is_modelled_only_for_the_transfer_agent():
    from steward.core.simulate import Unmodelled

    e = pipeline.load()
    gov = e.compiled["infra/governance/generated.tf.json"]
    assert "data_transfer_agent" in gov["resource"]["google_project_iam_member"]
    model(e.compiled["infra/estate/generated.tf.json"], gov)  # as generated: modelled
    for member in ('${var.principals["analyst@GR"]}', "serviceAccount:somebody@example.iam.gserviceaccount.com"):
        bad = copy.deepcopy(gov)
        bad["resource"]["google_project_iam_member"]["data_transfer_agent"]["member"] = member
        with pytest.raises(Unmodelled):
            model(e.compiled["infra/estate/generated.tf.json"], bad)


def test_compiled_output_is_deterministic():
    assert pipeline.load().rendered() == pipeline.load().rendered()


def test_columns_sharing_a_profile_share_a_tag():
    tags = pipeline.load().compiled_tags
    # identical classification and masking map → one tag
    assert tags["crm.customers.msisdn"] == tags["crm.support_tickets.ref_2"]
    assert tags["crm.customers.msisdn"] != tags["network.usage_events.msisdn"]  # personal vs sensitive-network
