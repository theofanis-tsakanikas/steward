"""Claim 2 live: a captured transcript is judged against the compiled controls, never against its own claims."""

from __future__ import annotations

import pytest

from steward import io, pipeline
from steward.core import access_live as al
from steward.core.simulate import answer, model

TABLE = "crm.customers"
COLUMNS = ["customer_id", "msisdn", "email", "birth_date", "country", "segment", "created_at"]


@pytest.fixture(scope="module")
def world():
    e = pipeline.load()
    am = model(e.compiled["infra/estate/generated.tf.json"], e.compiled["infra/governance/generated.tf.json"])
    rows = io.synthetic_rows(TABLE)
    types = {f["name"]: f["type"] for f in io.harvest()[TABLE]["fields"]}
    return am, rows, types


def _honest(am, seat, rows, types):
    """What a correct BigQuery would return: the simulator's own answer, as a transcript."""
    exp = answer(am, seat, TABLE, COLUMNS, rows, types)
    if "error" in exp:
        return exp, {"seat": seat, "table": TABLE, "outcome": "error", "error": exp["error"], "rows": []}
    return exp, {"seat": seat, "table": TABLE, "outcome": "rows", "rows": exp["rows"]}


def test_an_honest_transcript_of_every_seat_is_clean(world):
    am, rows, types = world
    for seat in ("analyst@GR", "fraud_investigator", "group:crm-stewards@halverra.example"):
        exp, tr = _honest(am, seat, rows, types)
        assert al.judge(tr, exp, rows, types) == [], seat


def test_a_value_that_was_not_masked_is_found(world):
    am, rows, types = world
    exp, tr = _honest(am, "analyst@GR", rows, types)
    assert tr["outcome"] == "rows"
    stored = {r["created_at"]: r for r in rows}
    tr["rows"][0]["msisdn"] = stored[tr["rows"][0]["created_at"]]["msisdn"]  # the raw value leaked
    codes = {f.code for f in al.judge(tr, exp, rows, types)}
    assert "LIVE_VALUE_NOT_MASKED" in codes


def test_rows_returned_to_a_seat_the_controls_deny_are_found(world):
    am, rows, types = world
    exp, _ = _honest(am, "fraud_investigator", rows, types)
    assert "error" in exp
    leaked = {"seat": "fraud_investigator", "table": TABLE, "outcome": "rows", "rows": [{"country": "GR"}]}
    assert [f.code for f in al.judge(leaked, exp, rows, types)] == ["LIVE_ACCESS_ALLOWED"]


def test_a_refusal_for_a_seat_the_controls_allow_is_found(world):
    am, rows, types = world
    exp, _ = _honest(am, "analyst@GR", rows, types)
    refused = {"seat": "analyst@GR", "table": TABLE, "outcome": "error", "error": "Access Denied: x", "rows": []}
    assert [f.code for f in al.judge(refused, exp, rows, types)] == ["LIVE_ACCESS_DENIED"]


def test_another_countrys_rows_are_found_by_count_or_by_match(world):
    am, rows, types = world
    exp, tr = _honest(am, "analyst@GR", rows, types)
    other = next(r for r in rows if r["country"] == "DE")
    tr["rows"][0] = {**tr["rows"][0], "country": "DE", "created_at": other["created_at"]}
    assert al.judge(tr, exp, rows, types)  # the DE clear values do not go with the GR masked values


def test_the_timestamp_notation_does_not_matter():
    assert al._same("2026-09-06T05:49:12Z", "2026-09-06T05:49:12+00:00")
    assert not al._same("2026-09-06T05:49:12Z", "2026-09-06T05:49:13Z")


@pytest.mark.parametrize(
    ("rule", "live", "true", "ok"),
    [
        ("ALWAYS_NULL", None, "x", True),
        ("ALWAYS_NULL", "x", "x", False),
        ("LAST_FOUR_CHARACTERS", "XXXXX1234", "+30691231234", True),
        ("LAST_FOUR_CHARACTERS", "+30691231234", "+30691231234", False),
        ("EMAIL_MASK", "XXXXX@example.org", "a.b@example.org", True),
        ("EMAIL_MASK", "a.b@example.org", "a.b@example.org", False),
        ("DATE_YEAR_MASK", "1988-01-01", "1988-05-17", True),
        ("DATE_YEAR_MASK", "1988-05-17", "1988-05-17", False),
        ("clear", "GR", "GR", True),
        ("clear", "XX", "GR", False),
    ],
)
def test_each_rule_has_a_property_the_live_value_must_satisfy(rule, live, true, ok):
    assert al.consistent(rule, live, true) is ok


def test_sha256_is_accepted_in_every_encoding_bigquery_might_use():
    import base64
    import hashlib

    raw = hashlib.sha256(b"CUST-1").digest()
    for live in (raw, base64.b64encode(raw).decode(), raw.hex()):
        assert al.consistent("SHA256", live, "CUST-1")
    assert not al.consistent("SHA256", "CUST-1", "CUST-1")
    assert not al.consistent("SHA256", "A" * 32, "CUST-1")
    other = base64.b64encode(hashlib.sha256(b"CUST-2").digest()).decode()
    assert not al.consistent("SHA256", other, "CUST-1")


def test_email_mask_is_exactly_the_bigquery_shape():
    assert al.consistent("EMAIL_MASK", "XXXXX@example.org", "a.b@example.org")
    assert not al.consistent("EMAIL_MASK", "a.person@example.org", "someone@example.org")


def test_a_row_from_another_country_fails_the_row_policy(world):
    am, rows, types = world
    exp, tr = _honest(am, "analyst@GR", rows, types)
    other = next(r for r in rows if r["country"] == "IT")
    tr["rows"][0] = {**tr["rows"][0], "country": "IT", "created_at": other["created_at"], "segment": other["segment"]}
    assert "LIVE_ROW_POLICY" in {f.code for f in al.judge(tr, exp, rows, types)}
