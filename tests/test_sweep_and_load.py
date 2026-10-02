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


EMPTY = {k: [] for k in sweep.KINDS}


def test_a_clean_project_sweeps_clean():
    inv = {
        **EMPTY,
        "buckets": [f"{P}-steward-tfstate"],
        "accounts": ["steward-deployer", "steward-destroyer", "steward-guard", "steward-reaper", "steward-build"],
    }
    assert sweep.leftovers(P, inv) == []


def test_every_kind_of_leftover_is_named():
    inv = {
        **EMPTY,
        "datasets": ["crm"],
        "buckets": [f"{P}-steward-tfstate", f"{P}-landing"],
        "accounts": ["seat-analyst-gr", "person-eleni-kosta", "steward-deployer"],
        "scans": ["steward-dq-crm-customers"],
        "templates": ["steward-inspect"],
        "exchanges": ["steward_marketplace"],
        "sinks": ["steward-data-access", "_Default"],
        "taxonomies": ["steward-classification"],
        "parameters": ["steward-estate"],
        "transfers": ["steward retention crm.customers (400 d)"],
    }
    left = sweep.leftovers(P, inv)
    assert "dataset crm" in left and f"bucket {P}-landing" in left
    assert "service account seat-analyst-gr" in left and "service account person-eleni-kosta" in left
    assert "log sink steward-data-access" in left and not any("_Default" in x for x in left)
    assert not any("steward-deployer" in x or "tfstate" in x for x in left)
    for kind in (
        "dataplex scan",
        "dlp inspect template",
        "analytics hub exchange",
        "policy-tag taxonomy",
        "parameter",
        "scheduled query",
    ):
        assert any(x.startswith(kind) for x in left), kind


def test_an_inventory_that_does_not_look_somewhere_is_refused_not_passed():
    import pytest

    for kind in sweep.KINDS:
        inv = {k: [] for k in sweep.KINDS if k != kind}
        with pytest.raises(ValueError, match=kind):
            sweep.leftovers(P, inv)


def test_no_listing_uses_a_gcloud_command_that_does_not_exist():
    # `gcloud dlp inspect-templates` and `gcloud bigquery analytics-hub` do not exist (gcloud 571): those
    # collections are read over REST. The gcloud commands that remain are the ones that do.
    src = (io.REPO / "scripts" / "sweep.py").read_text()
    assert '"dlp"' not in src and '"analytics-hub"' not in src  # no such gcloud groups are invoked
    assert set(sweep.REST) == {"scans", "templates", "exchanges", "taxonomies", "parameters", "transfers"}
    for url, key in sweep.REST.values():
        assert url.startswith("https://") and "{p}" in url and key


def test_every_synthetic_table_has_a_load_and_a_metadata_count():
    tables = load.tables()
    assert {f"{d}.{t}" for d, t, _ in tables} >= {"crm.customers", "finance.billing", "network.usage_events"}
    for d, t, p in tables:
        cmd = load.load_command(P, d, t, p)
        assert "--replace" in cmd and cmd[-2] == f"{d}.{t}" and Path(cmd[-1]).exists()
        show = load.show_command(P, d, t)
        assert "query" not in show and show[-1] == f"{P}:{d}.{t}"  # metadata only: no query to bound or filter


def test_a_count_that_differs_from_the_generator_is_a_mismatch():
    assert load.mismatches({"a.b": 3}, {"a.b": 3}) == []
    assert load.mismatches({"a.b": 2}, {"a.b": 3}) == ["a.b: loaded 2, generator wrote 3"]
    assert load.mismatches({}, {"a.b": 3})  # a table that never loaded
    assert load.mismatches({"a.b": None}, {"a.b": 3})  # a table that cannot be read


def test_the_row_count_is_read_from_metadata_and_unreadable_is_none():
    assert load.rows_in('{"numRows": "42"}') == 42
    for bad in ("", "not json", "{}", '{"numRows": "many"}', "[]"):
        assert load.rows_in(bad) is None


def test_a_row_count_that_appears_late_is_waited_for_and_a_wrong_one_is_not_forgiven():
    import importlib.util

    from steward import io

    spec = importlib.util.spec_from_file_location("load_synthetic", io.REPO / "scripts" / "load_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen = iter([None, None, 600])
    waits: list[float] = []
    assert mod.settled(lambda: next(seen), 600, attempts=5, pause=1, sleep=waits.append) == 600
    assert waits == [1, 1]
    # a table that really holds a different count is reported as that count, after the attempts run out
    assert mod.settled(lambda: 599, 600, attempts=3, pause=1, sleep=lambda _: None) == 599
    assert mod.settled(lambda: None, 600, attempts=3, pause=1, sleep=lambda _: None) is None


def test_a_notice_before_the_json_does_not_hide_the_row_count():
    import importlib.util

    from steward import io

    spec = importlib.util.spec_from_file_location("load_synthetic2", io.REPO / "scripts" / "load_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.rows_in('WARNING: --scopes flag may not work\n{"numRows": "600", "type": "TABLE"}\n') == 600
    assert mod.rows_in("not json") is None
    assert mod.rows_in('{"type": "TABLE"}') is None
