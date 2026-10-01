import copy
from datetime import date

import pytest

from steward import io
from steward.core.validate import validate_all

TODAY = date(2026, 10, 1)


@pytest.fixture
def base():
    return io.contract_docs(), io.roles_doc(), io.waivers_doc(), io.harvest()


def codes(findings, blocking_only=True):
    return {f.code for f in findings if f.blocking or not blocking_only}


def run(docs, roles, waivers, harvest, today=TODAY):
    return validate_all(docs, roles, waivers, harvest, today)[1]


def test_committed_contracts_are_green(base):
    assert codes(run(*base)) == set()


@pytest.mark.parametrize("field", ["owner", "steward", "custodian"])
def test_missing_owner_is_refused(base, field):
    docs, *rest = base
    docs = copy.deepcopy(docs)
    del docs["crm"][field]
    assert "OWNERSHIP_MISSING" in codes(run(docs, *rest))


def test_missing_retention_is_refused(base):
    docs, *rest = base
    docs = copy.deepcopy(docs)
    del docs["finance"]["retention"]
    assert "RETENTION_MISSING" in codes(run(docs, *rest))


def test_missing_legal_basis_is_refused(base):
    docs, *rest = base
    docs = copy.deepcopy(docs)
    del docs["network"]["retention"]["legal_basis"]
    assert "RETENTION_MISSING" in codes(run(docs, *rest))


def test_missing_classification_is_refused(base):
    docs, *rest = base
    docs = copy.deepcopy(docs)
    del docs["crm"]["tables"]["customers"]["columns"]["segment"]["classification"]
    assert "CLASSIFICATION_MISSING" in codes(run(docs, *rest))


def test_a_new_column_in_the_estate_is_drift(base):
    docs, roles, waivers, harvest = base
    harvest = copy.deepcopy(harvest)
    harvest["finance.billing"]["fields"].append({"name": "payer_phone", "type": "STRING", "mode": "NULLABLE"})
    assert "COLUMN_UNDECLARED" in codes(run(docs, roles, waivers, harvest))


def test_type_drift(base):
    docs, roles, waivers, harvest = base
    harvest = copy.deepcopy(harvest)
    next(f for f in harvest["finance.billing"]["fields"] if f["name"] == "amount")["type"] = "STRING"
    assert "TYPE_MISMATCH" in codes(run(docs, roles, waivers, harvest))


def test_waiver_expires_and_the_finding_returns(base):
    docs, roles, waivers, harvest = base
    out = run(docs, roles, waivers, harvest, today=date(2026, 12, 1))
    assert "CONTRACT_MISSING" in codes(out)
    assert "WAIVER_EXPIRED" in codes(out, blocking_only=False)


def test_unwaivable_finding_waiver_is_refused(base):
    docs, roles, waivers, harvest = base
    waivers = copy.deepcopy(waivers)
    waivers["waivers"].append(
        {
            "id": "W-999",
            "finding": "PII_UNTAGGED",
            "target": "crm.support_tickets.ref_2",
            "reason": "legacy usage, will fix",
            "approved_by": "user:dimitris.nikolaou@halverra.example",
            "approved_on": "2026-10-01",
            "expires": "2026-12-31",
        }
    )
    assert "WAIVER_REFUSED" in codes(run(docs, roles, waivers, harvest))


def test_service_account_cannot_approve_a_waiver(base):
    docs, roles, waivers, harvest = base
    waivers = copy.deepcopy(waivers)
    waivers["waivers"][0]["approved_by"] = "serviceAccount:steward-pipeline@halverra-data.example"
    out = run(docs, roles, waivers, harvest)
    assert "WAIVER_REFUSED" in codes(out) and "CONTRACT_MISSING" in codes(out)


def test_version_without_changelog_is_refused(base):
    docs, *rest = base
    docs = copy.deepcopy(docs)
    docs["crm"]["version"] = 2
    assert "CONTRACT_INVALID" in codes(run(docs, *rest))


def test_bad_principal_is_refused(base):
    docs, *rest = base
    docs = copy.deepcopy(docs)
    docs["crm"]["owner"] = "the crm team"
    assert "CONTRACT_INVALID" in codes(run(docs, *rest))


def test_masking_on_an_untagged_column_is_refused(base):
    docs, *rest = base
    docs = copy.deepcopy(docs)
    docs["crm"]["tables"]["customers"]["columns"]["segment"]["masking"] = {"analyst": "hash"}
    assert "CONTRACT_INVALID" in codes(run(docs, *rest))


def test_dangling_reference(base):
    docs, *rest = base
    docs = copy.deepcopy(docs)
    q = docs["finance"]["tables"]["billing"]["columns"]["customer_id"]["quality"][0]
    q["references"] = "crm.customer.customer_id"
    assert "REFERENCE_DANGLING" in codes(run(docs, *rest))
