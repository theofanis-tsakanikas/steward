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
