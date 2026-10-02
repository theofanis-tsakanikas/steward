"""The one bound on what a live scan may read: DLP's rows limit and Dataplex's sampling percentage."""

from __future__ import annotations

import pytest

from steward import io
from steward.core import sampling as sp


def test_a_small_table_is_read_whole_from_the_top():
    s = sp.plan_sample("crm.customers", 600, 371_371)
    assert s.complete and s.rows_limit == 600 and s.coverage == 1
    cfg = sp.dlp_storage_config("p", "crm", "customers", s)["big_query_options"]
    assert cfg["rows_limit"] == 600 and cfg["sample_method"] == "TOP"
    assert sp.dataplex_sampling_percent(s) == 100.0


def test_a_large_table_is_sampled_down_to_the_row_ceiling_from_a_random_start():
    s = sp.plan_sample("network.usage_events", 6_000_000, 1_000_000_000)
    assert s.rows_limit <= sp.MAX_INSPECT_ROWS and not s.complete
    assert (
        sp.dlp_storage_config("p", "network", "usage_events", s)["big_query_options"]["sample_method"] == "RANDOM_START"
    )
    assert s.estimated_bytes <= sp.MAX_INSPECT_BYTES


def test_the_byte_ceiling_binds_before_the_row_ceiling_for_wide_rows():
    s = sp.plan_sample("t.wide", 5_000, 5_000 * 1_000_000)  # 1 MB a row
    assert s.rows_limit == 33 and s.estimated_bytes <= sp.MAX_INSPECT_BYTES


@pytest.mark.parametrize("rows", [0, -5, True, 1.5, None])
def test_an_unknown_or_empty_table_is_refused_not_given_a_zero_limit(rows):
    with pytest.raises(ValueError):
        sp.plan_sample("t.t", rows, 10)


def test_a_row_wider_than_the_byte_ceiling_is_refused():
    with pytest.raises(ValueError, match="ceiling"):
        sp.plan_sample("t.t", 10, 10 * (sp.MAX_INSPECT_BYTES + 1))


def test_the_percentage_rounds_down_so_the_scan_never_reads_over_the_plan():
    for rows in (10_001, 12_345, 99_999, 1_000_003, 7_777_777):
        s = sp.plan_sample("t.t", rows, rows * 100)
        pct = sp.dataplex_sampling_percent(s)
        assert 0 < pct <= 100
        assert rows * pct / 100 <= s.rows_limit


def test_a_table_too_large_for_one_decimal_is_refused():
    s = sp.plan_sample("t.t", 10**9, 10**9)
    with pytest.raises(ValueError, match="one decimal"):
        sp.dataplex_sampling_percent(s)


def test_a_dlp_config_is_never_built_with_a_zero_or_oversized_limit():
    s = sp.plan_sample("a.b", 100, 100)
    for bad in (0, -1, sp.MAX_INSPECT_ROWS + 1):
        with pytest.raises(ValueError, match="outside"):
            sp.dlp_storage_config("p", "a", "b", sp.Sample("a.b", 100, 100, bad))
    with pytest.raises(ValueError, match="not"):
        sp.dlp_storage_config("p", "a", "other", s)


def test_the_evidence_record_says_how_much_was_read():
    r = sp.plan_sample("t.t", 40_000, 4_000_000).as_record()
    assert r["coverage"] == 0.25 and r["rows_limit"] == 10_000 and r["complete"] is False


def test_the_whole_synthetic_estate_is_inside_the_ceiling():
    for table, (rows, nbytes) in io.table_sizes().items():
        assert sp.plan_sample(table, rows, nbytes).complete, table
