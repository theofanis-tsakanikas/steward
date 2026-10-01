"""Evidence is deterministic, self-verifying, and a function of the repository."""

from __future__ import annotations

import json
import shutil

from steward import evidence


def test_the_committed_evidence_is_clean():
    assert [f.line() for f in evidence.check()] == []


def test_building_twice_gives_byte_identical_evidence():
    a, b = evidence.build_files(), evidence.build_files()
    assert {n: evidence.canonical(d) for n, d in a.items()} == {n: evidence.canonical(d) for n, d in b.items()}


def test_the_digest_covers_the_payload_not_the_envelope():
    d = {"a": [1, 2], "b": {"c": 3}}
    assert evidence.digest(d) == evidence.digest({"b": {"c": 3}, "a": [1, 2]})
    assert evidence.digest(d) != evidence.digest({"a": [1, 3], "b": {"c": 3}})


def test_load_refuses_a_payload_that_was_edited(tmp_path, monkeypatch):
    shutil.copytree(evidence.ROOT, tmp_path / "evidence")
    monkeypatch.setattr(evidence, "ROOT", tmp_path / "evidence")
    p = tmp_path / "evidence" / "fixture" / "retention.json"
    doc = json.loads(p.read_text())
    doc["data"]["findings"] = ["nothing to see"]
    p.write_text(json.dumps(doc))
    try:
        evidence.load("fixture", "retention")
    except ValueError as ex:
        assert "digest" in str(ex)
    else:
        raise AssertionError("tampered evidence was loaded")
    assert "EVIDENCE_DIGEST_MISMATCH" in {f.code for f in evidence.check()}


def test_a_missing_gates_record_is_a_finding_not_a_pass(tmp_path, monkeypatch):
    shutil.copytree(evidence.ROOT, tmp_path / "evidence")
    monkeypatch.setattr(evidence, "ROOT", tmp_path / "evidence")
    (tmp_path / "evidence" / "fixture" / "gates.json").unlink()
    assert "EVIDENCE_MISSING" in {f.code for f in evidence.check()}


def test_a_recorded_run_with_a_let_through_mutation_is_refused(tmp_path, monkeypatch):
    shutil.copytree(evidence.ROOT, tmp_path / "evidence")
    monkeypatch.setattr(evidence, "ROOT", tmp_path / "evidence")
    p = tmp_path / "evidence" / "fixture" / "gates.json"
    doc = json.loads(p.read_text())
    doc["data"]["results"][0]["status"] = "LET THROUGH"
    doc["meta"]["digest"] = evidence.digest(doc["data"])
    p.write_text(json.dumps(doc))
    evidence.write_manifest()
    assert "GATES_NOT_REFUSED" in {f.code for f in evidence.check()}
