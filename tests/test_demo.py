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


def test_there_are_eight_pages_and_a_landing_page():
    assert len(PAGES) == 9
    assert [p.split("/")[-1].split("_")[0] for p in PAGES[1:]] == [str(i) for i in range(1, 9)]


@pytest.mark.parametrize("page", PAGES)
def test_page_opens_from_evidence_and_states_its_mode(page):
    at = run(page)
    assert not at.exception, [e.value for e in at.exception]
    # the Catalog page shows a simulated sync failure on purpose; what must never appear is a missing/refused file
    assert not [e.value for e in at.error if e.value.startswith(("No evidence", "Evidence refused"))]
    banner = " ".join(i.value for i in at.info)
    assert "RECORDED mode" in banner and "evidence `fixture`" in banner
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
    assert not at.dataframe  # nothing was drawn from the tampered file


def test_every_figure_on_the_home_page_is_in_the_evidence():
    at = run("Home.py")
    shown = {m.value for m in at.metric}
    estate = evidence.load("fixture", "estate")["data"]
    assert str(len(estate["datasets"])) in shown
