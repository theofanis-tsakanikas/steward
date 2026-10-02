"""Claim 1, live: Sensitive Data Protection (DLP) inspects a bounded sample of every table the capture may read.

How, and why this way:

* The sample is a SELECT with a LIMIT from `core/sampling.plan_sample` (never more than the ceiling), read by the
  identity that is allowed to read the table: the dataset's custodian seat (it sees every row and holds no
  Fine-Grained Reader) for a contracted dataset, the deployer for a dataset no contract covers. A storage inspection
  job would run as the DLP service agent, which the row access policies filter to zero rows and which holds no tag
  reader, so it would either read nothing or need a grant no contract made (doctrine 1).
* Only columns with no policy tag are read. A tagged column is already declared sensitive: the gate that fails is
  the one for personal data in a column that carries no tag, and those are exactly the columns this reads.
* The rows go to `content.inspect` with the inspect template the assurance layer built (the same infoTypes the
  value detector can find); `include_quote` is false, so a finding never repeats the value. The request is chunked
  by rows; a response that DLP truncated is split and asked again, and a one-row truncation is recorded and refused.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from steward.core.compile_assurance import DLP_MAP
from steward.core.sampling import Sample

MAX_REQUEST_BYTES = 400_000  # the API limit is 0.5 MB
INFOTYPE_KIND = {name: kind for kind, (name, _rx) in DLP_MAP.items()}


def leaf_columns(fields: list[dict], prefix: str = "") -> list[tuple[str, str, bool]]:
    """(path, type, repeated) of every leaf of a BigQuery schema; a leaf under a REPEATED record is repeated."""
    out = []
    for f in fields:
        path = prefix + f["name"]
        rep = f.get("mode") == "REPEATED"
        if f.get("fields"):
            out += [(p, t, r or rep) for p, t, r in leaf_columns(f["fields"], path + ".")]
        else:
            out.append((path, f["type"], rep))
    return out


def select_list(columns: list[str]) -> str:
    """`address.city` is read as address.city and named address__city (a SELECT list cannot carry a dot alias)."""
    return ", ".join(f"CAST({c} AS STRING) AS `{c.replace('.', '__')}`" for c in columns)


def table_item(columns: list[str], rows: list[dict]) -> dict:
    """The rows as a DLP table item; a NULL becomes the empty string, which no detector matches."""
    names = [c.replace(".", "__") for c in columns]
    return {
        "table": {
            "headers": [{"name": n} for n in names],
            "rows": [{"values": [{"stringValue": "" if r.get(n) is None else str(r[n])} for n in names]} for r in rows],
        }
    }


def _size(rows: list[dict]) -> int:
    return sum(len(str(v)) + 8 for r in rows for v in r.values())


def chunks(rows: list[dict], max_bytes: int = MAX_REQUEST_BYTES) -> list[list[dict]]:
    out, cur, size = [], [], 0
    for r in rows:
        s = _size([r])
        if cur and size + s > max_bytes:
            out.append(cur)
            cur, size = [], 0
        cur.append(r)
        size += s
    return out + ([cur] if cur else [])


def parse_findings(result: dict, row_offset: int = 0) -> list[dict]:
    """[{column, info_type, likelihood, row}] from an `inspect` response. A finding names a column and a kind, no value."""
    out = []
    for f in result.get("findings", []):
        for loc in f.get("location", {}).get("contentLocations", []):
            rec = loc.get("recordLocation", {})
            out.append(
                {
                    "column": rec.get("fieldId", {}).get("name", ""),
                    "info_type": f["infoType"]["name"],
                    "likelihood": f.get("likelihood", "LIKELIHOOD_UNSPECIFIED"),
                    "row": int(rec.get("tableLocation", {}).get("rowIndex", 0)) + row_offset,
                }
            )
    return out


def inspect_rows(call, columns: list[str], rows: list[dict], offset: int = 0) -> tuple[list[dict], bool, int]:
    """Inspect `rows`; `call(item) -> response dict`. Returns (findings, truncated, requests made).

    A response flagged `findingsTruncated` is not used: the rows are split in halves and asked again, so the findings
    that come back are complete. One row that still truncates is returned as truncated (the caller refuses it)."""
    result = call(table_item(columns, rows))
    if not result.get("result", result).get("findingsTruncated"):
        return parse_findings(result.get("result", result), offset), False, 1
    if len(rows) == 1:
        return parse_findings(result.get("result", result), offset), True, 1
    mid = len(rows) // 2
    a, ta, na = inspect_rows(call, columns, rows[:mid], offset)
    b, tb, nb = inspect_rows(call, columns, rows[mid:], offset + mid)
    return a + b, ta or tb, na + nb + 1


def summarize(table: str, findings: list[dict]) -> list[dict]:
    """One line per (column, infoType): how many findings and at which likelihoods. No value, no row number."""
    per: dict[tuple[str, str], Counter] = defaultdict(Counter)
    rows: dict[tuple[str, str], set] = defaultdict(set)
    for f in findings:
        per[(f["column"], f["info_type"])][f["likelihood"]] += 1
        rows[(f["column"], f["info_type"])].add(f["row"])
    return [
        {
            "table": table,
            "column": col.replace("__", "."),
            "info_type": it,
            "kind": INFOTYPE_KIND.get(it),
            "findings": sum(c.values()),
            "rows_with_a_finding": len(rows[(col, it)]),
            "likelihoods": dict(sorted(c.items())),
        }
        for (col, it), c in sorted(per.items())
    ]


def sample_record(s: Sample) -> dict:
    return s.as_record()
