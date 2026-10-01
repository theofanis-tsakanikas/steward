import copy
from datetime import date

import pytest

from steward import io, pipeline
from steward.core.classify import detect, detect_column, scan_value
from steward.core.gate_classification import gate

SCAN = date(2026, 9, 30)


@pytest.fixture(scope="module")
def detections():
    return detect(io.synthetic_columns(), SCAN)


def run(detections, docs=None, harvest=None):
    e = pipeline.load(contract_docs=docs, harvest=harvest)
    return {(f.code, f.target) for f in gate(detections, e.contracts, e.compiled_tags, e.broken) if f.blocking}


def test_committed_contracts_pass(detections):
    assert run(detections) == set()


def test_downgraded_ref_2_is_refused(detections):
    docs = copy.deepcopy(io.contract_docs())
    docs["crm"]["tables"]["support_tickets"]["columns"]["ref_2"] = {
        "type": "STRING",
        "classification": "internal",
        "description": "an internal reference",
    }
    assert run(detections, docs) == {("PII_UNTAGGED", "crm.support_tickets.ref_2")}


def test_undeclared_column_with_pii_is_refused(detections):
    docs = copy.deepcopy(io.contract_docs())
    del docs["finance"]["tables"]["billing"]["columns"]["iban"]
    assert ("PII_UNDECLARED_COLUMN", "finance.billing.iban") in run(detections, docs)


def test_under_declared_kinds_are_refused(detections):
    docs = copy.deepcopy(io.contract_docs())
    docs["crm"]["tables"]["support_tickets"]["columns"]["notes_free_text"]["kinds"] = ["msisdn"]
    assert run(detections, docs) == {("KIND_UNDECLARED", "crm.support_tickets.notes_free_text")}


def test_broken_contract_blocks_its_pii_in_this_gate(detections):
    docs = copy.deepcopy(io.contract_docs())
    del docs["finance"]["owner"]
    assert ("PII_CONTRACT_BROKEN", "finance.billing.iban") in run(detections, docs)


def test_uncontracted_table_passes_only_when_compiled_restricted(detections):
    e = pipeline.load()
    tags = dict(e.compiled_tags)
    assert tags["legacy.legacy_crm_export.tel_a"] == "restricted"
    tags["legacy.legacy_crm_export.tel_a"] = None  # a compiler that forgot the safe state
    out = {(f.code, f.target) for f in gate(detections, e.contracts, tags, e.broken) if f.blocking}
    assert out == {("PII_UNTAGGED", "legacy.legacy_crm_export.tel_a")}


def test_detector_never_reads_column_names():
    vals = ["+306912345678"] * 10
    assert (
        detect_column("crm.customers.msisdn", vals, SCAN).kinds
        == detect_column("x.y.unrelated", vals, SCAN).kinds
        == ["msisdn"]
    )


def test_imei_and_imsi_are_scored_independently_in_a_mixed_column():
    imeis = ["490154203237518", "356938035643809", "352099001761481"]
    imsis = ["262011234567890", "202971234567891", "222975555555555"]
    assert detect_column("a", imeis * 3, SCAN).kinds == ["imei"]
    assert detect_column("b", imsis * 3, SCAN).kinds == ["imsi"]
    assert detect_column("c", imeis + imsis + ["123"], SCAN).kinds == ["imei", "imsi"]


def test_one_hit_is_enough():
    # doctrine 1: two e-mails in fifty rows is a column holding e-mails
    assert detect_column("a", ["nothing"] * 48 + ["x@example.com", "y@example.org"], SCAN).kinds == ["email"]
    assert detect_column("b", ["call +306912345678"], SCAN).kinds == ["msisdn"]


def test_history_is_not_a_birth_date_column():
    created = [f"{y}-03-01" for y in range(1990, 2009)] + ["2020-01-01"] * 5
    assert "birth_date" not in detect_column("a", created, SCAN).kinds
    births = [f"{y}-03-01" for y in range(1940, 2000)]
    assert detect_column("b", births, SCAN).kinds == ["birth_date"]


def test_birth_date_window_moves_with_the_scan_date():
    assert "birth_date" in scan_value("2009-01-01", date(2026, 1, 1))
    assert "birth_date" not in scan_value("2011-01-01", date(2026, 1, 1))


def test_unschemed_fields_are_scanned():
    from steward.core.classify import column_values

    vals = column_values(
        [{"a": 1, "rec": "x@example.com", "extra": "+306912345678"}],
        [
            {"name": "a", "type": "INTEGER"},
            {"name": "rec", "type": "RECORD", "fields": [{"name": "b", "type": "STRING"}]},
        ],
    )
    assert vals["rec"] == ["x@example.com"] and vals["__unschemed__.extra"] == ["+306912345678"]
