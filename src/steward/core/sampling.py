"""How much of a table a live scan may read - one bound, used by every scan that bills per byte or row.

DLP inspects what its job config names and Dataplex scans what `sampling_percent` allows; neither has a ceiling
of its own. DLP even treats `rows_limit = 0` as "no limit", so an unset or zeroed limit is the one value that
turns a sample into a full-table scan. This module is where the ceiling lives, so that:

* a scan is planned from the table's size (rows and bytes) and never from a hope that the table is small;
* a table whose size is unknown, empty or negative stops the build (doctrine 3: no invented size, and an empty
  table must not become `rows_limit = 0`);
* the part of the table a scan covers is a number that travels with the evidence (doctrine 2: a scan that read
  a tenth of a table says so).

Pure functions over plain numbers. The adapters read the sizes (INFORMATION_SCHEMA / `numRows`) and pass them in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MAX_INSPECT_ROWS = 10_000
MAX_INSPECT_BYTES = 32 * 1024 * 1024
# Dataplex takes a percentage with one decimal; below this a "sample" would be a handful of rows.
MIN_SAMPLING_PERCENT = 0.1


@dataclass(frozen=True)
class Sample:
    table: str
    num_rows: int
    num_bytes: int
    rows_limit: int  # always >= 1 and <= MAX_INSPECT_ROWS

    @property
    def coverage(self) -> float:
        """The share of the table the scan reads, 0 < c <= 1."""
        return self.rows_limit / self.num_rows

    @property
    def complete(self) -> bool:
        return self.rows_limit >= self.num_rows

    @property
    def estimated_bytes(self) -> int:
        return math.ceil(self.num_bytes * self.coverage)

    def as_record(self) -> dict:
        """What the evidence says about the sample (it is written next to the findings)."""
        return {
            "table": self.table,
            "num_rows": self.num_rows,
            "rows_limit": self.rows_limit,
            "coverage": round(self.coverage, 6),
            "complete": self.complete,
            "estimated_bytes": self.estimated_bytes,
        }


def _whole(name: str, x: object, table: str) -> int:
    if isinstance(x, bool) or not isinstance(x, int):
        raise ValueError(f"{table}: {name} must be an integer, got {x!r}")
    return x


def plan_sample(
    table: str,
    num_rows: int,
    num_bytes: int,
    *,
    max_rows: int = MAX_INSPECT_ROWS,
    max_bytes: int = MAX_INSPECT_BYTES,
) -> Sample:
    """The rows a scan of `table` may read: all of them when the table fits both ceilings, else as many as fit."""
    num_rows, num_bytes = _whole("num_rows", num_rows, table), _whole("num_bytes", num_bytes, table)
    if num_rows <= 0:
        raise ValueError(f"{table}: {num_rows} rows - nothing to inspect (and a zero limit means unlimited to DLP)")
    if num_bytes < 0:
        raise ValueError(f"{table}: negative size {num_bytes}")
    if max_rows < 1 or max_bytes < 1:
        raise ValueError("the ceilings must be positive")
    per_row = max(num_bytes / num_rows, 1)
    limit = min(num_rows, max_rows, math.floor(max_bytes / per_row))
    if limit < 1:
        raise ValueError(f"{table}: one row averages {per_row:.0f} bytes, over the {max_bytes}-byte ceiling")
    return Sample(table, num_rows, num_bytes, limit)


def dataplex_sampling_percent(s: Sample) -> float:
    """`sampling_percent` for a Dataplex scan: rounded DOWN to one decimal, so the scan never reads more than the
    plan allows (rounding up could read 0.1% of a large table over the ceiling)."""
    if s.complete:
        return 100.0
    pct = math.floor(s.coverage * 1000) / 10
    if pct < MIN_SAMPLING_PERCENT:
        raise ValueError(f"{s.table}: {s.num_rows} rows cannot be sampled within {s.rows_limit} rows at one decimal")
    return pct


def dlp_storage_config(project: str, dataset: str, table: str, s: Sample) -> dict:
    """The `storageConfig` of a DLP inspection job: the rows limit is always set, never zero, never above the ceiling.

    A complete sample reads from the top, so the result is reproducible. A partial one starts at a random row:
    reading the top of a table biases the sample towards its oldest rows, and the evidence records the coverage."""
    if f"{dataset}.{table}" != s.table:
        raise ValueError(f"sample is for {s.table}, not {dataset}.{table}")
    if not 1 <= s.rows_limit <= MAX_INSPECT_ROWS:
        raise ValueError(f"{s.table}: rows_limit {s.rows_limit} is outside 1..{MAX_INSPECT_ROWS}")
    return {
        "big_query_options": {
            "table_reference": {"project_id": project, "dataset_id": dataset, "table_id": table},
            "rows_limit": s.rows_limit,
            "sample_method": "TOP" if s.complete else "RANDOM_START",
        }
    }
