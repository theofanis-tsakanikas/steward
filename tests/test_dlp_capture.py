"""The DLP capture: bounded reads of untagged columns only, chunked and re-asked on truncation."""

from __future__ import annotations

import json

import pytest

from steward import io, pipeline
from steward.adapters import capture, dlp

PROJECT = "steward-test-123456"


@pytest.fixture(scope="module")
def e():
    return pipeline.load()


def test_leaf_columns_flatten_records_and_mark_repeated_ones():
    fields = [
        {"name": "id", "type": "STRING"},
        {"name": "address", "type": "RECORD", "fields": [{"name": "city", "type": "STRING"}]},
        {"name": "contracts", "type": "RECORD", "mode": "REPEATED", "fields": [{"name": "plan", "type": "STRING"}]},
    ]
    assert dlp.leaf_columns(fields) == [
        ("id", "STRING", False),
        ("address.city", "STRING", False),
        ("contracts.plan", "STRING", True),
    ]


def test_a_select_list_names_a_nested_leaf_without_a_dot():
    assert (
        dlp.select_list(["address.city", "id"])
        == "CAST(address.city AS STRING) AS `address__city`, CAST(id AS STRING) AS `id`"
    )


def test_a_null_is_the_empty_string_and_the_header_has_no_dot():
    item = dlp.table_item(["address.city"], [{"address__city": None}, {"address__city": "Athens"}])["table"]
    assert item["headers"] == [{"name": "address__city"}]
    assert [r["values"][0]["stringValue"] for r in item["rows"]] == ["", "Athens"]


def test_chunks_respect_the_request_size():
    rows = [{"a": "x" * 1000} for _ in range(100)]
    parts = dlp.chunks(rows, max_bytes=20_000)
    assert sum(len(p) for p in parts) == 100 and len(parts) > 3
    assert all(dlp._size(p) <= 20_000 + 1100 for p in parts)


def test_a_truncated_response_is_split_and_asked_again():
    calls = []

    def call(item):
        n = len(item["table"]["rows"])
        calls.append(n)
        if n > 2:
            return {"result": {"findingsTruncated": True, "findings": []}}
        return {
            "result": {
                "findings": [
                    {
                        "infoType": {"name": "EMAIL_ADDRESS"},
                        "likelihood": "LIKELY",
                        "location": {
                            "contentLocations": [
                                {"recordLocation": {"fieldId": {"name": "c"}, "tableLocation": {"rowIndex": "0"}}}
                            ]
                        },
                    }
                ]
            }
        }

    found, truncated, requests = dlp.inspect_rows(call, ["c"], [{"c": str(i)} for i in range(8)])
    assert not truncated and len(found) == 4  # four 2-row pieces, one finding each
    assert sorted(f["row"] for f in found) == [0, 2, 4, 6]  # row numbers are kept across the split
    assert requests == len(calls)


def test_one_row_that_still_truncates_is_reported_as_truncated():
    call = lambda item: {"result": {"findingsTruncated": True, "findings": []}}  # noqa: E731
    assert dlp.inspect_rows(call, ["c"], [{"c": "x"}])[1] is True


def test_the_summary_names_column_kind_and_count_never_a_value():
    f = [{"column": "address__city", "info_type": "EMAIL_ADDRESS", "likelihood": "LIKELY", "row": 3}] * 2
    (line,) = dlp.summarize("crm.customers", f)
    assert line["column"] == "address.city" and line["kind"] == "email" and line["findings"] == 2
    assert set(line) == {"table", "column", "info_type", "kind", "findings", "rows_with_a_finding", "likelihoods"}


def _capture(e, inspect=None, meta=None):
    reads = []

    def read_rows(who, sql):
        reads.append((who, sql))
        table = sql.split("FROM `")[1].split("`")[0]
        return [{c.replace(".", "__"): "x" for c in _cols(sql)}] * 3 if table else []

    def _cols(sql):
        return [
            p.split(" AS ")[0].replace("CAST(", "").strip()
            for p in sql[len("SELECT ") : sql.index(" FROM")].split(", ")
        ]

    def table_meta(t):
        return meta(t) if meta else {"numRows": "3", "numBytes": "300"}

    data = capture.capture_dlp(
        PROJECT, table_meta=table_meta, read_rows=read_rows, inspect=inspect or (lambda item: {"result": {}}), e=e
    )
    return data, reads


def test_tagged_and_repeated_columns_are_never_selected(e):
    data, reads = _capture(e)
    tags = e.compiled_tags
    for t in data["tables"]:
        for c in t["columns_scanned"]:
            assert tags.get(f"{t['table']}.{c}") is None
        for s in t["columns_not_scanned"]:
            assert s["reason"].startswith(("policy-tagged", "repeated"))
    sql = " ".join(s for _, s in reads)
    assert "customer_id" not in sql and "msisdn" not in sql.split("crm.customers")[1].split("FROM")[0]


def test_a_contracted_dataset_is_read_as_its_custodian_and_the_undeclared_one_is_held_at_the_safe_state_unread(e):
    data, reads = _capture(e)
    who = {sql.split("FROM `")[1].split("`")[0]: w for w, sql in reads}
    assert who["crm.customers"].startswith("seat-data-platform@")
    # an uncontracted dataset has every column held at the safe state (policy-tagged, denied to all): nobody may read
    # it, DLP included, and the evidence says so instead of reading it with an identity that happens to be strong
    assert "legacy.legacy_crm_export" not in who
    legacy = next(t for t in data["tables"] if t["table"] == "legacy.legacy_crm_export")
    assert legacy["rows_read"] == 0 and all(
        c["reason"].startswith("policy-tagged") for c in legacy["columns_not_scanned"]
    )


def test_every_read_is_limited_and_a_partitioned_table_carries_its_predicate(e):
    _, reads = _capture(e)
    for _, sql in reads:
        assert " LIMIT 3" in sql
    assert any("event_date >=" in sql for _, sql in reads if "network.usage_events" in sql)


def test_a_table_over_the_ceiling_is_sampled_not_read_whole(e):
    data, reads = _capture(e, meta=lambda t: {"numRows": "5000000", "numBytes": "500000000"})
    assert all(t["sample"]["rows_limit"] <= 10_000 and not t["sample"]["complete"] for t in data["tables"])
    assert all(int(sql.rsplit(" LIMIT ", 1)[1]) <= 10_000 for _, sql in reads)


def test_the_evidence_carries_no_project_id(e):
    data, _ = _capture(e)
    assert PROJECT not in json.dumps(data)


def test_every_synthetic_table_is_covered(e):
    data, _ = _capture(e)
    assert {t["table"] for t in data["tables"]} == set(io.harvest())


def test_control_sample_is_inspected_with_the_same_template_and_records_no_ground_truth():
    from steward.adapters import capture

    seen = []

    def inspect(item):
        seen.append(item)
        return {"result": {}}

    doc = capture._dlp_control(None, inspect)
    assert doc["rows_per_table"] == capture.CONTROL_ROWS
    assert seen and {t["table"] for t in doc["tables"]} >= {"crm.customers", "crm.support_tickets"}
    assert all(t["rows"] <= capture.CONTROL_ROWS for t in doc["tables"])
    # nothing about what was planted where is written down
    assert "planted" not in str(doc)


def test_history_is_captured_with_principals_named_and_the_sql_listing_only_estate_datasets():
    from steward.adapters import capture

    rows = [
        {
            "job_type": "LOAD",
            "statement_type": None,
            "creation_time": "2026-10-02T06:00:00Z",
            "principal": "deployer@steward-x.iam.gserviceaccount.com",
            "destination": "crm.customers",
            "referenced_tables": [],
        }
    ]
    seen = []

    def run(email, sql):
        seen.append((email, sql))
        return {"outcome": "rows", "rows": rows}

    doc = capture.capture_history("steward-x", run, capture.redactor("steward-x"), ["crm", "audit"])
    assert seen[0][0] is None and "'audit', 'crm'" in seen[0][1] and "INFORMATION_SCHEMA.JOBS_BY_PROJECT" in seen[0][1]
    assert doc["jobs"][0]["destination"] == "crm.customers" and "steward-x" not in str(doc["jobs"])


def test_a_table_with_every_column_tagged_is_not_read_at_all(e):
    """BigQuery refuses `SELECT  FROM t` (first capture, 2026-10-02): such a table is recorded as having nothing to read."""

    def read_rows(who, sql):
        assert not sql.startswith("SELECT  FROM"), sql
        return [{"x": "1"}]

    data = capture.capture_dlp(
        PROJECT,
        table_meta=lambda t: {"numRows": "3", "numBytes": "300"},
        read_rows=read_rows,
        inspect=lambda item: {"result": {}},
        e=e,
    )
    nothing = [t for t in data["tables"] if not t["columns_scanned"]]
    assert nothing and all(t["rows_read"] == 0 and t["requests"] == 0 for t in nothing)
