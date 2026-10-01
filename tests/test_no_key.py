"""Doctrine 7 (ADR 0007): no exception mechanism reaches the classification gate."""

import copy
import inspect
from datetime import date

from steward import io, pipeline
from steward.core import gate_classification
from steward.core.classify import detect
from steward.core.validate import validate_all


def test_the_gate_has_no_waiver_parameter():
    params = set(inspect.signature(gate_classification.gate).parameters)
    assert not {p for p in params if "waiver" in p or "exception" in p}


def test_a_pii_waiver_is_refused_and_the_scan_still_blocks():
    docs = copy.deepcopy(io.contract_docs())
    docs["crm"]["tables"]["support_tickets"]["columns"]["ref_2"] = {
        "type": "STRING",
        "classification": "internal",
        "description": "an internal reference",
    }
    waivers = copy.deepcopy(io.waivers_doc())
    waivers["waivers"].append(
        {
            "id": "W-777",
            "finding": "PII_UNTAGGED",
            "target": "crm.support_tickets.ref_2",
            "reason": "the business needs this column open",
            "requested_by": "user:katerina.vasileiou@halverra.example",
            "approved_by": "user:dimitris.nikolaou@halverra.example",
            "approved_on": date(2026, 10, 1),
            "expires": date(2026, 10, 30),
        }
    )
    _, contract_findings = validate_all(docs, io.roles_doc(), waivers, io.harvest(), date(2026, 10, 1))
    assert any(f.code == "WAIVER_REFUSED" and f.target == "W-777" and f.blocking for f in contract_findings)
    e = pipeline.load(contract_docs=docs)
    scan = gate_classification.gate(
        detect(io.synthetic_columns(), pipeline.synthetic_anchor()), e.contracts, e.compiled_tags, e.broken
    )
    assert any(f.code == "PII_UNTAGGED" and f.target == "crm.support_tickets.ref_2" and f.blocking for f in scan)


def test_the_gate_cannot_reach_a_waiver():
    import ast
    from pathlib import Path

    src = Path(gate_classification.__file__).read_text()
    imported = {(n.module or "") for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
    names = {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not any("validate" in m for m in imported) and "Waiver" not in names


def test_scan_cli_ignores_any_waiver_file(monkeypatch, capsys):
    from steward import cli

    docs = copy.deepcopy(io.contract_docs())
    docs["crm"]["tables"]["support_tickets"]["columns"]["ref_2"] = {
        "type": "STRING",
        "classification": "internal",
        "description": "an internal reference",
    }
    pii_waiver = {
        "waivers": [
            {
                "id": "W-777",
                "finding": "PII_UNTAGGED",
                "target": "crm.support_tickets.ref_2",
                "reason": "the business needs this open",
                "requested_by": "user:katerina.vasileiou@halverra.example",
                "approved_by": "user:dimitris.nikolaou@halverra.example",
                "approved_on": date(2026, 10, 1),
                "expires": date(2026, 10, 30),
            }
        ]
    }
    monkeypatch.setattr(io, "contract_docs", lambda root=None: copy.deepcopy(docs))
    monkeypatch.setattr(io, "waivers_doc", lambda root=None: pii_waiver)
    assert cli.main(["scan"]) == 1
    assert "PII_UNTAGGED crm.support_tickets.ref_2" in capsys.readouterr().out


def test_removing_the_data_clears_the_finding(monkeypatch):
    """Doctrine 7's only exit besides tagging: remove the values, and the scan comes back clean."""
    docs = copy.deepcopy(io.contract_docs())
    docs["crm"]["tables"]["support_tickets"]["columns"]["ref_2"] = {
        "type": "STRING",
        "classification": "internal",
        "description": "an internal reference",
    }
    cols = io.synthetic_columns()
    cols["crm.support_tickets.ref_2"] = [
        None if v and v.startswith("+") else v for v in cols["crm.support_tickets.ref_2"]
    ]
    e = pipeline.load(contract_docs=docs)
    out = {
        (f.code, f.target)
        for f in gate_classification.gate(
            detect(cols, pipeline.synthetic_anchor()), e.contracts, e.compiled_tags, e.broken
        )
        if f.blocking
    }
    assert out == set()


def _sink_detection(table: str, kinds: list[str]):
    from steward.core.classify import ColumnDetection

    return ColumnDetection(
        f"audit.{table}.protopayload_auditlog.authenticationInfo.principalEmail", 10, {k: 10 for k in kinds}, kinds
    )


def test_log_sink_info_only_for_loggings_tables_and_kinds():
    e = pipeline.load()
    ok = gate_classification.gate(
        [_sink_detection("cloudaudit_googleapis_com_data_access", ["email"])], e.contracts, e.compiled_tags, e.broken
    )
    assert [(f.code, f.severity) for f in ok] == [("PII_IN_LOG_SINK", "info")]
    extra = gate_classification.gate(
        [_sink_detection("cloudaudit_googleapis_com_data_access", ["email", "msisdn"])],
        e.contracts,
        e.compiled_tags,
        e.broken,
    )
    assert [f.code for f in extra if f.blocking] == ["PII_UNDECLARED_COLUMN"]
    foreign = gate_classification.gate(
        [_sink_detection("customers_copy", ["email"])], e.contracts, e.compiled_tags, e.broken
    )
    assert [f.code for f in foreign if f.blocking] == ["PII_UNDECLARED_COLUMN"]


def _bump(new, *, requested_by, approved_by, ceilings_added=()):
    new["version"] += 1
    new["changes"].append(
        {
            "version": new["version"],
            "date": "2026-10-02",
            "change": "a change under test here",
            "requested_by": requested_by,
            "approved_by": approved_by,
            "ceilings_added": list(ceilings_added),
        }
    )


KAT, DIM = "user:katerina.vasileiou@halverra.example", "user:dimitris.nikolaou@halverra.example"


def codes_of(old, new):
    from steward.core.versioning import compare_roles

    return sorted({f.code for f in compare_roles(old, new)})


def test_a_ceiling_raise_needs_a_version_an_approval_and_a_listing():
    old = io.roles_doc()
    new = copy.deepcopy(old)
    new["ceilings"]["bi_service"]["clear_kinds"] = ["msisdn"]
    assert codes_of(old, new) == ["CEILING_RAISED", "ROLES_CHANGE_UNAPPROVED"]
    _bump(new, requested_by=KAT, approved_by=DIM)  # approved, but the ceiling is not listed
    assert codes_of(old, new) == ["CEILING_RAISED"]
    new["changes"][-1]["ceilings_added"] = [{"role": "bi_service", "kinds": ["msisdn"]}]
    assert codes_of(old, new) == []


def test_self_approval_and_unknown_approver_are_refused():
    old = io.roles_doc()
    new = copy.deepcopy(old)
    _bump(new, requested_by=DIM, approved_by=DIM)
    assert codes_of(old, new) == ["ROLES_CHANGE_UNAPPROVED"]
    new = copy.deepcopy(old)
    _bump(new, requested_by=KAT, approved_by="user:anna.christou@halverra.example")
    assert codes_of(old, new) == ["ROLES_CHANGE_UNAPPROVED"]


def test_adding_yourself_to_the_approver_group_in_the_same_pr_does_not_help():
    old = io.roles_doc()
    new = copy.deepcopy(old)
    new["directory"]["group:privacy-office@halverra.example"].append("user:anna.christou@halverra.example")
    _bump(new, requested_by=KAT, approved_by="user:anna.christou@halverra.example")
    assert codes_of(old, new) == ["ROLES_CHANGE_UNAPPROVED"]


def test_an_old_approval_cannot_be_reused():
    old = io.roles_doc()
    old_lowered = copy.deepcopy(old)
    old_lowered["ceilings"]["fraud_investigator"]["clear_kinds"] = ["imsi"]  # the base after a lowering
    new = copy.deepcopy(old_lowered)
    new["ceilings"]["fraud_investigator"]["clear_kinds"] = ["imsi", "msisdn"]  # raised again, citing v1
    _bump(new, requested_by=KAT, approved_by=DIM)
    assert codes_of(old_lowered, new) == ["CEILING_RAISED"]


def test_history_is_append_only_and_a_missing_base_fails_closed():
    old = io.roles_doc()
    new = copy.deepcopy(old)
    new["changes"][0]["change"] = "rewritten after the fact"
    assert "ROLES_HISTORY_REWRITTEN" in codes_of(old, new)
    assert codes_of(None, io.roles_doc()) == ["ROLES_BASE_MISSING"]


def test_a_bound_role_may_see_nothing_in_clear():
    import pytest
    from pydantic import ValidationError

    from steward.core.contract import Roles

    roles = copy.deepcopy(io.roles_doc())
    roles["ceilings"]["steward"]["clear_kinds"] = ["email"]
    with pytest.raises(ValidationError, match="bound role"):
        Roles.model_validate(roles)


def test_a_log_sink_dataset_is_read_by_its_steward_alone():
    from steward.core.validate import load_contract

    doc = copy.deepcopy(io.contract_docs()["audit"])
    doc["readers"] = ["steward", "analyst"]
    assert load_contract("audit", doc)[0] is None
