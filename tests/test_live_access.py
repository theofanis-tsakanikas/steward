"""The live access capture and its offline re-check, with a runner that answers like a correct BigQuery."""

from __future__ import annotations

import json

import pytest

from steward import evidence, io, live, pipeline
from steward.adapters import capture
from steward.core.simulate import model

PROJECT = "steward-test-123456"


@pytest.fixture(scope="module")
def e():
    return pipeline.load()


def _honest_runner(e):
    am = model(e.compiled["infra/estate/generated.tf.json"], e.compiled["infra/governance/generated.tf.json"])
    seats = json.loads((io.REPO / "infra" / "seats.json").read_text())
    by_email = {f"{v}@{PROJECT}.iam.gserviceaccount.com": k for k, v in {**seats["seats"], **seats["people"]}.items()}
    by_sql = {q.sql(): q for q in live.QUERIES}

    def run(email, sql):
        q, seat = by_sql[sql], by_email[email]
        exp = live.expected_answer(e, am, q, seat)
        if "error" in exp:
            return {"outcome": "error", "error": f"Access Denied: Table {PROJECT}:{q.table}: {exp['error']}"}
        return {"outcome": "rows", "rows": exp["rows"], "job_id": "job_x", "bytes_billed": 10485760}

    return run


def test_a_correct_estate_gives_evidence_that_verifies_clean(e):
    data = capture.capture_access(PROJECT, _honest_runner(e), e, capture.redactor(PROJECT))
    assert live.verify_access(data, e) == []
    assert all(PROJECT not in json.dumps(t) for t in data["transcripts"])  # nothing identifies the project


def test_every_declared_seat_has_a_transcript(e):
    data = capture.capture_access(PROJECT, _honest_runner(e), e)
    got = {(t["query"], t["seat"]) for t in data["transcripts"]}
    for q in live.QUERIES:
        for s in q.seats:
            assert (q.id, live.resolve(e, q, s)) in got


def test_an_estate_that_masks_nothing_is_found(e):
    honest = _honest_runner(e)

    def leaky(email, sql):
        res = honest(email, sql)
        if res["outcome"] == "rows":
            q = next(q for q in live.QUERIES if q.sql() == sql)
            stored = {r["created_at"] if q.id == "customers" else r["event_id"]: r for r in io.synthetic_rows(q.table)}
            key = "created_at" if q.id == "customers" else "event_id"
            res = {**res, "rows": [{**r, "msisdn": stored[r[key]]["msisdn"]} for r in res["rows"]]}
        return res

    data = capture.capture_access(PROJECT, leaky, e)
    codes = {f.code for f in live.verify_access(data, e)}
    assert "LIVE_VALUE_NOT_MASKED" in codes


def test_a_missing_transcript_is_found(e):
    data = capture.capture_access(PROJECT, _honest_runner(e), e)
    data["transcripts"].pop(0)
    assert "LIVE_TRANSCRIPT_MISSING" in {f.code for f in live.verify_access(data, e)}


def test_written_evidence_is_a_live_document_with_its_digest(e, tmp_path):
    data = capture.capture_access(PROJECT, _honest_runner(e), e)
    path = capture.write("access", data, "2", "test", data["captured_at"], out=tmp_path)
    doc = json.loads(path.read_text())
    assert doc["meta"]["mode"] == "live" and doc["meta"]["digest"] == evidence.digest(doc["data"])
