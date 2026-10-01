import copy
from datetime import date

import pytest
import yaml

from steward import io
from steward.core.validate import validate_all
from steward.core.versioning import compare

TODAY = date(2026, 10, 1)


@pytest.fixture
def base():
    return copy.deepcopy((io.contract_docs(), io.roles_doc(), io.waivers_doc(), io.harvest()))


def blocking(findings):
    return {(f.code, f.target) for f in findings if f.blocking}


def run(docs, roles, waivers, harvest, today=TODAY):
    return validate_all(docs, roles, waivers, harvest, today)[1]


def test_committed_contracts_are_green(base):
    assert blocking(run(*base)) == set()


@pytest.mark.parametrize("field", ["owner", "steward", "custodian"])
def test_missing_owner_is_refused(base, field):
    docs, *rest = base
    del docs["crm"][field]
    assert ("OWNERSHIP_MISSING", f"crm:{field}") in blocking(run(docs, *rest))


@pytest.mark.parametrize("value", ["__delete__", None])
def test_missing_or_null_retention_is_refused(base, value):
    docs, *rest = base
    if value == "__delete__":
        del docs["finance"]["retention"]
    else:
        docs["finance"]["retention"] = None
    assert ("RETENTION_MISSING", "finance:retention") in blocking(run(docs, *rest))


def test_missing_legal_basis_is_refused(base):
    docs, *rest = base
    del docs["network"]["retention"]["legal_basis"]
    assert ("RETENTION_MISSING", "network:retention.legal_basis") in blocking(run(docs, *rest))


def test_legal_basis_must_name_an_instrument(base):
    docs, *rest = base
    docs["network"]["retention"]["legal_basis"] = "xxxxxxxxxxxx"
    assert ("CONTRACT_INVALID", "network:retention.legal_basis") in blocking(run(docs, *rest))


@pytest.mark.parametrize("value", ["__delete__", None])
def test_missing_or_null_classification_is_refused(base, value):
    docs, *rest = base
    col = docs["crm"]["tables"]["customers"]["columns"]["segment"]
    if value == "__delete__":
        del col["classification"]
    else:
        col["classification"] = None
    assert ("CLASSIFICATION_MISSING", "crm:tables.customers.columns.segment.classification") in blocking(
        run(docs, *rest)
    )


def test_row_access_is_required(base):
    docs, *rest = base
    del docs["crm"]["tables"]["customers"]["row_access"]
    assert ("ROW_ACCESS_MISSING", "crm:tables.customers.row_access") in blocking(run(docs, *rest))


def test_row_access_none_needs_a_reason_and_is_accepted_with_one(base):
    docs, *rest = base
    docs["crm"]["tables"]["customers"]["row_access"] = {"none": "customer master is global by design"}
    assert blocking(run(docs, *rest)) == set()


def test_row_access_on_a_tagged_column_is_refused(base):
    docs, *rest = base
    docs["crm"]["tables"]["customers"]["row_access"] = {"column": "msisdn"}
    out = blocking(run(docs, *rest))
    assert ("ROW_ACCESS_ON_TAGGED", "crm.customers") in out and ("ROW_ACCESS_UNSCOPED", "crm.customers") in out


def test_a_new_column_in_the_estate_is_drift(base):
    docs, roles, waivers, harvest = base
    harvest["finance.billing"]["fields"].append({"name": "payer_phone", "type": "STRING", "mode": "NULLABLE"})
    assert blocking(run(docs, roles, waivers, harvest)) == {("COLUMN_UNDECLARED", "finance.billing.payer_phone")}


def test_type_drift(base):
    docs, roles, waivers, harvest = base
    next(f for f in harvest["finance.billing"]["fields"] if f["name"] == "amount")["type"] = "STRING"
    assert blocking(run(docs, roles, waivers, harvest)) == {("TYPE_MISMATCH", "finance.billing.amount")}


def test_partition_retention_must_match_the_estate_partition(base):
    docs, *rest = base
    docs["network"]["tables"]["usage_events"]["retention"]["column"] = "event_ts"
    assert ("RETENTION_PARTITION_MISMATCH", "network.usage_events") in blocking(run(docs, *rest))


# ── waivers ──────────────────────────────────────────────────────────────────────────────────────


def _waiver(**kw):
    w = {
        "id": "W-900",
        "finding": "CONTRACT_MISSING",
        "target": "legacy.legacy_crm_export",
        "reason": "a test waiver here",
        "requested_by": "user:katerina.vasileiou@halverra.example",
        "approved_by": "user:dimitris.nikolaou@halverra.example",
        "approved_on": date(2026, 10, 1),
        "expires": date(2026, 11, 1),
    }
    w.update(kw)
    return w


def test_waiver_expires_and_the_finding_returns(base):
    docs, roles, waivers, harvest = base
    out = run(docs, roles, waivers, harvest, today=date(2026, 12, 1))
    assert ("CONTRACT_MISSING", "legacy.legacy_crm_export") in blocking(out)
    assert any(f.code == "WAIVER_EXPIRED" and f.target == "W-001" for f in out)


@pytest.mark.parametrize(
    "finding,target",
    [
        ("PII_UNTAGGED", "crm.support_tickets.ref_2"),
        ("RETENTION_MISSING", "finance:retention"),
        ("COLUMN_UNDECLARED", "finance.billing.payer_phone"),
    ],
)
def test_only_contract_missing_is_waivable(base, finding, target):
    docs, roles, waivers, harvest = base
    waivers["waivers"].append(_waiver(id="W-901", finding=finding, target=target))
    assert ("WAIVER_REFUSED", "W-901") in blocking(run(docs, roles, waivers, harvest))


def test_waiver_longer_than_90_days_is_invalid(base):
    docs, roles, waivers, harvest = base
    waivers["waivers"][0]["expires"] = date(9999, 12, 31)
    out = blocking(run(docs, roles, waivers, harvest))
    assert ("WAIVER_INVALID", "W-001") in out and ("CONTRACT_MISSING", "legacy.legacy_crm_export") in out


@pytest.mark.parametrize(
    "approver,why",
    [
        ("serviceAccount:steward-pipeline@halverra-data.example", "service account"),
        ("user:mallory@evil.example", "not in the approver group"),
        ("user:katerina.vasileiou@halverra.example", "the requester"),
    ],
)
def test_waiver_approver_is_checked(base, approver, why):
    docs, roles, waivers, harvest = base
    waivers["waivers"][0]["approved_by"] = approver
    out = blocking(run(docs, roles, waivers, harvest))
    assert ("WAIVER_REFUSED", "W-001") in out and ("CONTRACT_MISSING", "legacy.legacy_crm_export") in out, why


def test_owner_cannot_waive_own_dataset(base):
    docs, roles, waivers, harvest = base
    roles["waiver_approvers"] = "group:crm-owners@halverra.example"
    waivers["waivers"] = [
        _waiver(finding="TABLE_UNDECLARED", target="crm.loyalty", approved_by="user:eleni.papadaki@halverra.example")
    ]
    harvest["crm.loyalty"] = {"partition": None, "fields": [{"name": "x", "type": "STRING", "mode": "NULLABLE"}]}
    assert ("WAIVER_REFUSED", "W-900") in blocking(run(docs, roles, waivers, harvest))


def test_future_approval_and_duplicates_and_unused_are_refused(base):
    docs, roles, waivers, harvest = base
    waivers["waivers"].append(_waiver(id="W-002"))  # duplicate of W-001
    waivers["waivers"].append(
        _waiver(id="W-003", target="legacy.other", approved_on=date(2026, 10, 20), expires=date(2026, 11, 1))
    )
    out = blocking(run(docs, roles, waivers, harvest))
    assert ("WAIVER_REFUSED", "W-002") in out
    assert ("WAIVER_REFUSED", "W-003") in out


def test_unused_waiver_is_an_error(base):
    docs, roles, waivers, harvest = base
    waivers["waivers"].append(_waiver(id="W-004", target="legacy.nothing_here"))
    assert ("WAIVER_UNUSED", "W-004") in blocking(run(docs, roles, waivers, harvest))


def test_unparseable_waiver_is_a_finding_not_a_crash(base):
    docs, roles, waivers, harvest = base
    waivers["waivers"][0]["expires"] = "soon"
    assert ("WAIVER_INVALID", "W-001") in blocking(run(docs, roles, waivers, harvest))


# ── separation of duties ─────────────────────────────────────────────────────────────────────────


def test_service_account_group_cannot_own_or_approve(base):
    docs, *rest = base
    docs["crm"]["owner"] = "group:data-platform@halverra.example"
    docs["crm"]["marketplace"]["approvers"] = "group:data-platform@halverra.example"
    out = blocking(run(docs, *rest))
    assert ("DUTY_NOT_HUMAN", "crm.owner") in out
    assert ("DUTY_CONFLICT", "crm.owner") in out
    assert ("DUTY_CONFLICT", "crm.marketplace.approvers") in out


def test_kinds_are_a_closed_vocabulary(base):
    docs, *rest = base
    docs["crm"]["tables"]["support_tickets"]["columns"]["ref_2"]["kinds"] = ["zzz"]
    assert ("CONTRACT_INVALID", "crm:tables.support_tickets.columns.ref_2.kinds.0") in blocking(run(docs, *rest))


def test_quality_rule_must_fit_the_column_type(base):
    docs, *rest = base
    docs["finance"]["tables"]["billing"]["columns"]["status"]["quality"][0] = {
        "id": "Q-FIN-006",
        "kind": "validity",
        "min": 5,
    }
    assert any(
        c == "CONTRACT_INVALID" and t.startswith("finance:tables.billing.columns.status")
        for c, t in blocking(run(docs, *rest))
    )


def test_version_without_changelog_is_refused(base):
    docs, *rest = base
    docs["crm"]["version"] = 2
    assert ("CONTRACT_INVALID", "crm") in blocking(run(docs, *rest))


def test_bad_principal_is_refused(base):
    docs, *rest = base
    docs["crm"]["owner"] = "the crm team"
    assert ("CONTRACT_INVALID", "crm:owner") in blocking(run(docs, *rest))


def test_masking_on_an_untagged_column_is_refused(base):
    docs, *rest = base
    docs["crm"]["tables"]["customers"]["columns"]["segment"]["masking"] = {"analyst": "hash"}
    assert ("CONTRACT_INVALID", "crm:tables.customers.columns.segment") in blocking(run(docs, *rest))


def test_dangling_reference(base):
    docs, *rest = base
    docs["finance"]["tables"]["billing"]["columns"]["customer_id"]["quality"][0]["references"] = (
        "crm.customer.customer_id"
    )
    assert ("REFERENCE_DANGLING", "finance.billing.customer_id") in blocking(run(docs, *rest))


# ── loader and versions ──────────────────────────────────────────────────────────────────────────


def test_duplicate_yaml_key_is_refused(tmp_path):
    p = tmp_path / "x.yaml"
    p.write_text("a: 1\nref_2: {classification: personal}\nref_2: {classification: internal}\n")
    with pytest.raises(io.DuplicateKeyError):
        io.load_yaml(p)


def test_yml_extension_is_refused(tmp_path):
    (tmp_path / "x.yml").write_text("a: 1\n")
    with pytest.raises(ValueError, match="yml"):
        io.contract_docs(tmp_path)


def test_changed_contract_must_bump_version():
    old = yaml.safe_load((io.CONTRACTS / "crm.yaml").read_text())
    new = copy.deepcopy(old)
    new["tables"]["support_tickets"]["columns"]["ref_2"]["classification"] = "internal"
    assert [f.code for f in compare("crm", old, new)] == ["VERSION_NOT_BUMPED"]
    new["version"] = 2
    new["changelog"].append({"version": 2, "date": "2026-10-02", "change": "x"})
    assert compare("crm", old, new) == []
    new["changelog"][0]["change"] = "rewritten"
    assert [f.code for f in compare("crm", old, new)] == ["CHANGELOG_REWRITTEN"]
    assert [f.code for f in compare("crm", old, None)] == ["CONTRACT_DELETED"]
