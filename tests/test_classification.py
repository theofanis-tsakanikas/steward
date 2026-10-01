import copy
from datetime import date

import pytest

from steward import io
from steward.core.classify import detect, detect_column, scan_value
from steward.core.gate_classification import gate
from steward.core.validate import load_contract

SCAN = date(2026, 9, 30)


@pytest.fixture(scope="module")
def detections():
    return detect(io.synthetic_columns(), SCAN)


def contracts(docs):
    return [load_contract(n, d)[0] for n, d in docs.items()]


def codes(findings):
    return {(f.code, f.target) for f in findings if f.blocking}


def test_committed_contracts_pass(detections):
    assert codes(gate(detections, contracts(io.contract_docs()))) == set()


def test_downgraded_ref_2_is_refused(detections):
    docs = copy.deepcopy(io.contract_docs())
    docs["crm"]["tables"]["support_tickets"]["columns"]["ref_2"] = {
        "type": "STRING",
        "classification": "internal",
        "description": "an internal reference",
    }
    assert codes(gate(detections, contracts(docs))) == {("PII_UNTAGGED", "crm.support_tickets.ref_2")}


def test_undeclared_column_with_pii_is_refused(detections):
    docs = copy.deepcopy(io.contract_docs())
    del docs["finance"]["tables"]["billing"]["columns"]["iban"]
    assert ("PII_UNDECLARED_COLUMN", "finance.billing.iban") in codes(gate(detections, contracts(docs)))


def test_under_declared_kinds_are_refused(detections):
    docs = copy.deepcopy(io.contract_docs())
    docs["crm"]["tables"]["support_tickets"]["columns"]["notes_free_text"]["kinds"] = ["msisdn"]
    assert codes(gate(detections, contracts(docs))) == {("KIND_UNDECLARED", "crm.support_tickets.notes_free_text")}


def test_detector_never_reads_column_names():
    vals = ["+306912345678"] * 10
    a = detect_column("crm.customers.msisdn", vals, SCAN)
    b = detect_column("x.y.totally_unrelated", vals, SCAN)
    assert a.kinds == b.kinds == ["msisdn"]


def test_imei_and_imsi_are_told_apart_per_column():
    imeis = ["490154203237518", "356938035643809", "353918057470734", "358240051111110"] * 3
    imsis = ["262011234567890", "202971234567891", "222975555555555", "262970000000012"] * 3
    assert detect_column("a", imeis, SCAN).kinds == ["imei"]
    assert detect_column("b", imsis, SCAN).kinds == ["imsi"]


def test_rare_hits_below_threshold_are_not_flagged():
    vals = ["nothing here"] * 500 + ["call +306912345678"] * 2
    assert detect_column("a", vals, SCAN).kinds == []


def test_birth_date_window_moves_with_the_scan_date():
    assert "birth_date" in scan_value("2009-01-01", date(2026, 1, 1))
    assert "birth_date" not in scan_value("2011-01-01", date(2026, 1, 1))
