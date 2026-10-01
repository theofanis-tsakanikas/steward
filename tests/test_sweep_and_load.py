"""The two scripts that run only against a live project are tested on their decisions."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from steward import io


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, io.REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sweep, load = _load("sweep"), _load("load_synthetic")
P = "steward-demo-1"


def test_a_clean_project_sweeps_clean():
    inv = {"buckets": [f"{P}-steward-tfstate"], "accounts": ["steward-deployer", "steward-guard", "steward-build"]}
    assert sweep.leftovers(P, inv) == []


def test_every_kind_of_leftover_is_named():
    inv = {
        "datasets": ["crm"],
        "buckets": [f"{P}-steward-tfstate", f"{P}-landing"],
        "accounts": ["seat-analyst-gr", "person-eleni-kosta", "steward-deployer"],
        "scans": ["steward-dq-crm-customers"],
        "templates": ["steward-inspect"],
        "exchanges": ["steward_marketplace"],
        "sinks": ["steward-data-access", "_Default"],
    }
    left = sweep.leftovers(P, inv)
    assert "dataset crm" in left and f"bucket {P}-landing" in left
    assert "service account seat-analyst-gr" in left and "service account person-eleni-kosta" in left
    assert "log sink steward-data-access" in left and not any("_Default" in x for x in left)
    assert not any("steward-deployer" in x or "tfstate" in x for x in left)


def test_every_synthetic_table_has_a_load_and_a_bounded_count():
    tables = load.tables()
    assert {f"{d}.{t}" for d, t, _ in tables} >= {"crm.customers", "finance.billing", "network.usage_events"}
    for d, t, p in tables:
        cmd = load.load_command(P, d, t, p)
        assert "--replace" in cmd and cmd[-2] == f"{d}.{t}" and Path(cmd[-1]).exists()
        count = load.count_command(P, d, t)
        assert any(a.startswith("--maximum_bytes_billed=") for a in count)  # CLAUDE.md: every query is bounded


def test_a_count_that_differs_from_the_generator_is_a_mismatch():
    assert load.mismatches({"a.b": 3}, {"a.b": 3}) == []
    assert load.mismatches({"a.b": 2}, {"a.b": 3}) == ["a.b: loaded 2, generator wrote 3"]
    assert load.mismatches({}, {"a.b": 3})  # a table that never loaded
