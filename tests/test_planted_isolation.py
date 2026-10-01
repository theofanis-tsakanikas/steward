"""The planted ground truth is read by evals only — proved at runtime, not by grepping source.

The audit hook (tests/conftest.py) is installed before any steward import and records every `open`
and every subprocess. A production path that read the ground truth — by name, through a symlink, from a
copy, or by shelling out — fails here.
"""

import os
import shutil
from datetime import date

from conftest import AUDIT, is_ground_truth
from steward import io, pipeline
from steward.core.classify import detect
from steward.core.compile import check
from steward.core.gate_classification import gate
from steward.core.validate import validate_all


def test_production_paths_never_open_the_ground_truth():
    start_open, start_sub = len(AUDIT["open"]), len(AUDIT["subprocess"])
    validate_all(io.contract_docs(), io.roles_doc(), io.waivers_doc(), io.harvest(), date(2026, 10, 1))
    e = pipeline.load()
    check(e.contracts, e.roles)
    e.rendered()
    gate(detect(io.synthetic_columns(), pipeline.synthetic_anchor()), e.contracts, e.compiled_tags, e.broken)
    opened = AUDIT["open"][start_open:]
    assert opened, "the hook saw nothing — it is not wired"
    assert [p for p in opened if is_ground_truth(p)] == []
    assert AUDIT["subprocess"][start_sub:] == [], "production paths must not shell out"


def test_imports_did_not_read_it_either():
    # everything opened since the hook was installed — including at import time
    assert [p for p in AUDIT["open"] if is_ground_truth(p) and "test_" not in p] == []


def test_the_hook_sees_symlinks_and_copies(tmp_path):
    link, dup = tmp_path / "innocent_link", tmp_path / "innocent_copy.json"
    os.symlink(io.REPO / "evals" / "ground_truth" / "planted.json", link)
    shutil.copy(io.REPO / "evals" / "ground_truth" / "planted.json", dup)
    start = len(AUDIT["open"])
    link.read_text()
    dup.read_text()
    assert sum(is_ground_truth(p) for p in AUDIT["open"][start:]) == 2
