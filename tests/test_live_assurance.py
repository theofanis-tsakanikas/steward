from steward.core import live_assurance as la

TAGS = {"crm.t.email": "personal", "crm.t.note": None, "crm.t.id": None}


def dlp(findings=(), control=None, truncated=False, complete=True):
    ctl = (
        control
        if control is not None
        else [
            {
                "table": "crm.t",
                "column": "email",
                "info_type": "EMAIL_ADDRESS",
                "kind": "email",
                "rows_with_a_finding": 3,
            },
            {"table": "crm.t", "column": "iban", "info_type": "IBAN_CODE", "kind": "iban", "rows_with_a_finding": 3},
        ]
    )
    return {
        "tables": [
            {
                "table": "crm.t",
                "truncated": truncated,
                "sample": {"complete": complete, "rows_limit": 5, "num_rows": 9, "coverage": 5 / 9},
            }
        ],
        "findings": list(findings),
        "control": {"tables": [{"table": "crm.t", "truncated": False}], "findings": ctl},
    }


def codes(fs):
    return sorted(f.code for f in fs if f.blocking)


def test_clean_answer_is_clean():
    assert la.verify_dlp(dlp(), TAGS, {"crm.t"}) == []


def test_personal_data_in_an_untagged_column_is_blocking_and_not_waivable_by_shape():
    f = {"table": "crm.t", "column": "note", "info_type": "PHONE_NUMBER", "kind": "msisdn", "rows_with_a_finding": 2}
    assert codes(la.verify_dlp(dlp([f]), TAGS, {"crm.t"})) == ["LIVE_DLP_UNTAGGED"]


def test_a_finding_in_a_tagged_column_is_expected():
    f = {"table": "crm.t", "column": "email", "info_type": "EMAIL_ADDRESS", "kind": "email", "rows_with_a_finding": 2}
    assert la.verify_dlp(dlp([f]), TAGS, {"crm.t"}) == []


def test_a_truncated_answer_is_refused_and_a_missing_table_is_named():
    out = la.verify_dlp(dlp(truncated=True), TAGS, {"crm.t", "crm.other"})
    assert codes(out) == ["LIVE_DLP_TABLE_MISSING", "LIVE_DLP_TRUNCATED"]


def test_a_blind_control_makes_an_empty_answer_worthless():
    assert codes(la.verify_dlp(dlp(control=[]), TAGS, {"crm.t"})) == ["LIVE_DLP_CONTROL_BLIND"] * 2
    no_control = dlp()
    del no_control["control"]
    assert codes(la.verify_dlp(no_control, TAGS, {"crm.t"})) == ["LIVE_DLP_CONTROL_BLIND"]


def test_a_partial_sample_is_reported_not_blocking():
    out = la.verify_dlp(dlp(complete=False), TAGS, {"crm.t"})
    assert [f.code for f in out] == ["LIVE_DLP_PARTIAL"] and not out[0].blocking


def scan(sid="steward-dq-finance-billing", state="SUCCEEDED", rows=10, rules=None):
    return {
        "scan": sid,
        "state": state,
        "message": "",
        "rows_scanned": rows,
        "rules": rules or [{"rule": "q-fin-002", "failed_rows": 2}],
    }


COUNTS = {"finance.billing": 10, "crm.customers": 5}


def test_dataplex_agrees_with_the_offline_engine():
    assert la.verify_dataplex({"scans": [scan()]}, COUNTS, {"Q-FIN-002": 2}) == []


def test_dataplex_count_disagreement_is_a_finding():
    out = la.verify_dataplex({"scans": [scan()]}, COUNTS, {"Q-FIN-002": 3})
    assert codes(out) == ["LIVE_DQ_COUNT"]


def test_a_scan_that_did_not_succeed_and_a_rule_nobody_ran():
    out = la.verify_dataplex({"scans": [scan(state="FAILED")]}, COUNTS, {"Q-FIN-002": 2})
    assert codes(out) == ["LIVE_DQ_NOT_RUN", "LIVE_DQ_RULE_MISSING"]


def test_a_sampled_scan_is_not_compared_but_it_does_not_hide_a_rule_that_was_quarantined():
    out = la.verify_dataplex({"scans": [scan(rows=4)]}, COUNTS, {"Q-FIN-002": 2})
    assert [f.code for f in out if not f.blocking] == ["LIVE_DQ_PARTIAL"]
    assert codes(out) == ["LIVE_DQ_RULE_MISSING"]


def test_scan_ids_map_back_to_tables():
    assert la.scan_table("steward-dq-crm-customers", ["crm.customers"]) == "crm.customers"
    assert la.scan_table("steward-dq-nope", ["crm.customers"]) is None
