"""The demo opens every page from evidence alone, says what mode it is in, and refuses tampered evidence."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from steward import evidence, io

APP = io.REPO / "app"
PAGES = ["Home.py", *sorted(f"pages/{p.name}" for p in (APP / "pages").glob("*.py"))]


def run(page: str) -> AppTest:
    return AppTest.from_file(str(APP / page), default_timeout=120).run()


def test_there_are_nine_pages_and_a_landing_page():
    assert len(PAGES) == 10
    assert [p.split("/")[-1].split("_")[0] for p in PAGES[1:]] == [str(i) for i in range(1, 10)]


@pytest.mark.parametrize("page", PAGES)
def test_page_opens_from_evidence_and_states_its_mode(page):
    at = run(page)
    assert not at.exception, [e.value for e in at.exception]
    # the Catalog page shows a simulated sync failure on purpose; what must never appear is a missing/refused file
    assert not [e.value for e in at.error if e.value.startswith(("No evidence", "Evidence refused"))]
    banner = " ".join(i.value for i in at.info)
    assert "labelled" in banner.lower()
    assert "data as of" not in banner
    assert "Collibra mode: MOCK" in banner and "no Collibra instance was called" in banner
    assert "Fictional operator" in banner


def test_tampered_evidence_is_refused_not_shown(tmp_path, monkeypatch):
    copy = tmp_path / "evidence"
    shutil.copytree(evidence.ROOT, copy)
    p = copy / "fixture" / "quality.json"
    doc = json.loads(p.read_text())
    worst = max(doc["data"]["counts"].values(), key=lambda c: c["quarantined"])
    assert worst["quarantined"] > 0
    worst["quarantined"] = 0  # a quarantine quietly emptied
    p.write_text(json.dumps(doc))
    monkeypatch.setattr(evidence, "ROOT", Path(copy))
    at = run("pages/4_Quality.py")
    assert any("Evidence refused" in e.value for e in at.error)
    assert not at.dataframe  # fixture refused before any table was drawn


def test_every_figure_on_the_home_page_is_in_the_evidence():
    at = run("Home.py")
    shown = {m.value for m in at.metric}
    estate = evidence.load("fixture", "estate")["data"]
    assert str(len(estate["datasets"])) in shown
    captions = " ".join(c.value for c in at.caption)
    assert "Claim all seven" not in captions
    assert "Seven claims" in captions


def test_the_live_page_judges_a_capture_again_and_refuses_a_tampered_one(tmp_path, monkeypatch):
    """An honest capture is shown with its offline verdict; one edited by hand is refused, not shown."""
    from steward import live, pipeline
    from steward.adapters import capture
    from test_live_access import PROJECT, _honest_runner

    copy = tmp_path / "evidence"
    shutil.copytree(evidence.ROOT, copy)
    monkeypatch.setattr(evidence, "ROOT", Path(copy))
    e = pipeline.load()
    data = capture.capture_access(PROJECT, _honest_runner(e), e, capture.redactor(PROJECT))
    assert live.verify_access(data, e) == []
    capture.write("access", data, "2", "test", data["captured_at"])
    at = run("pages/9_Live.py")
    assert not at.exception, [x.value for x in at.exception]
    assert any("Re-judged offline" in s.value for s in at.success)
    assert "access" in " ".join(i.value for i in at.info)

    p = copy / "live" / "access.json"
    doc = json.loads(p.read_text())
    doc["data"]["transcripts"][0]["rows"] = []  # a transcript quietly emptied
    p.write_text(json.dumps(doc))
    at = run("pages/9_Live.py")
    assert any("Live evidence refused" in x.value for x in at.error)
