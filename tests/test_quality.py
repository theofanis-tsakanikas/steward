import copy
import json
from datetime import UTC, date, datetime

import pytest

from steward import io, pipeline, quality_run
from steward.core.gate_quality import gate
from steward.core.quality import run
from steward.core.validate import load_contract

TODAY = date(2026, 9, 30)


def billing_contract():
    return load_contract("finance", io.contract_docs()["finance"])[0]


def codes(findings):
    return {(f.code, f.target) for f in findings if f.blocking}


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    out = tmp_path_factory.mktemp("q")
    e = pipeline.load()
    summary = quality_run.load_all(e.contracts, out, TODAY, when=datetime(2026, 9, 30, tzinfo=UTC))
    return out, sorted(summary["tables"])


def test_reconciles_on_the_committed_data(written):
    out, tables = written
    counts, q = quality_run.read_destination(out, tables)
    assert codes(gate(counts, q)) == set()


def test_a_row_dropped_after_the_engine_is_caught(written, tmp_path):
    out, tables = written
    import shutil

    copy_ = tmp_path / "out"
    shutil.copytree(out, copy_)
    qf = copy_ / "finance.billing" / "quarantine.jsonl"
    lines = qf.read_text().splitlines()
    qf.write_text("\n".join(lines[1:]) + "\n")  # a loader that "forgets" one quarantined row
    counts, q = quality_run.read_destination(copy_, tables)
    assert codes(gate(counts, q)) == {("QUALITY_ROWS_LOST", "finance.billing")}


def test_unattributed_and_payloadless_records_are_refused():
    counts = {"t": {"source": 1, "loaded": 0, "quarantined": 1}}
    rec = {"run_id": "r", "table": "t", "row_key": "k@0", "rule_ids": [], "routed_to": "group:x@y.example"}
    out = codes(gate(counts, {"t": [rec]}))
    assert ("QUARANTINE_UNATTRIBUTED", "t") in out and ("QUARANTINE_PAYLOAD_MISSING", "t") in out


def test_first_occurrence_loads_later_duplicates_quarantine():
    c = billing_contract()
    rows = [json.loads(line) for line in (io.SYNTHETIC / "data" / "finance.billing.jsonl").read_text().splitlines()][:3]
    rows.append(copy.deepcopy(rows[0]))
    refs = {"crm.customers.customer_id": {r["customer_id"] for r in rows}}
    res = run(c, "billing", rows, refs, "r1", TODAY)
    assert [q.offset for q in res.quarantined] == [3] and res.quarantined[0].rule_ids == ["Q-FIN-002"]
    assert len(res.loaded) == 3


def test_a_row_failing_two_rules_is_quarantined_once_with_both():
    c = billing_contract()
    row = json.loads((io.SYNTHETIC / "data" / "finance.billing.jsonl").read_text().splitlines()[0])
    row["amount"] = "-1.00"
    row["customer_id"] = "C-nobody"
    res = run(c, "billing", [row], {"crm.customers.customer_id": set()}, "r", TODAY)
    assert len(res.quarantined) == 1 and res.quarantined[0].rule_ids == ["Q-FIN-003", "Q-FIN-004"]


def test_missing_reference_quarantines_rather_than_passes():
    c = billing_contract()
    row = json.loads((io.SYNTHETIC / "data" / "finance.billing.jsonl").read_text().splitlines()[0])
    res = run(c, "billing", [row], {}, "r", TODAY)
    assert res.quarantined and "not available" in res.quarantined[0].failures[0]["reason"]


def test_nested_repeated_validity():
    c = load_contract("crm", io.contract_docs()["crm"])[0]
    row = json.loads((io.SYNTHETIC / "data" / "crm.customers.jsonl").read_text().splitlines()[0])
    row["contracts"][0]["status"] = "paused"
    res = run(c, "customers", [row], {}, "r", TODAY)
    assert res.quarantined[0].rule_ids == ["Q-CRM-006"]


def test_freshness_goes_stale_as_time_passes():
    c = load_contract("network", io.contract_docs()["network"])[0]
    rows = io.synthetic_rows("network.usage_events")[:200]
    assert not run(c, "usage_events", rows, {}, "r", TODAY).findings
    stale = run(c, "usage_events", rows, {}, "r", date(2026, 12, 1)).findings
    assert [f.code for f in stale] == ["FRESHNESS_STALE"] and stale[0].evidence["routed_to"] == c.owner


def test_quarantine_tables_carry_the_source_tags():
    tags = pipeline.load().compiled_tags
    assert tags["finance.billing__quarantine.iban"] == tags["finance.billing.iban"] is not None
    assert tags["finance.billing__quarantine._rule_ids"] is None
