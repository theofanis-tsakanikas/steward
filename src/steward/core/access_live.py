"""Claim 2, live side: judge a captured query transcript against what the compiled Terraform says the seat must see.

The capture (adapters/capture.py) runs one query as each seat and writes down what BigQuery answered. This module
never talks to GCP: it takes the transcript and the simulator's answer (core/simulate.py `answer`, which reads the
compiled Terraform and never a contract) and says where they disagree. The check runs again offline, in CI, on the
committed evidence, so the live run is evidence and the comparison is code.

A masked value is judged by what the rule promises about it, not by byte equality with the simulator's own
rendering: the simulator's SHA-256 rendering is its own, and BigQuery's is BigQuery's. "Masked" must still mean
something, so each rule has a property the live value has to satisfy against the true value (which the caller reads
from the synthetic data the estate was loaded from).

  LIVE_ACCESS_ALLOWED      the simulator says denied, BigQuery returned rows
  LIVE_ACCESS_DENIED       the simulator says rows, BigQuery refused
  LIVE_ROWS                the number of rows differs from the row access policy's prediction
  LIVE_VALUE_NOT_MASKED    a masked column came back equal to the stored value (or in a shape the rule never yields)
  LIVE_VALUE_UNKNOWN       no stored row has the values the seat sees in clear (a clear column came back different)
  LIVE_ROW_POLICY          a returned row fails the seat's row access policy (the predicate the compiled Terraform names)
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime

from .findings import Finding
from .simulate import _row_passes

CLAIM = "2"


def _digests(true) -> set:
    raw = hashlib.sha256(str(true).encode()).digest()
    return {raw, base64.b64encode(raw).decode(), raw.hex(), raw.hex().upper()}


def _text(x) -> str:
    return x.decode("utf-8", "replace") if isinstance(x, bytes) else str(x)


def consistent(rule: str, live, true, col_type: str = "STRING") -> bool:
    """Does `live` look like what `rule` yields for `true`? ('clear' means equal.)"""
    if rule == "clear":
        return _text(live) == _text(true) if live is not None else true is None
    if true is None:
        return live is None
    if rule == "ALWAYS_NULL":
        return live is None
    if live is None:
        return False
    if rule == "SHA256":
        return live in _digests(true)
    if rule == "LAST_FOUR_CHARACTERS":
        return _text(live) != _text(true) and _text(live).endswith(_text(true)[-4:])
    if rule == "EMAIL_MASK":
        # BigQuery EMAIL_MASK is exactly XXXXX@domain (docs, 2026-10-01); any other local-part is a leak.
        s, t = _text(live), _text(true)
        return "@" in t and s == "XXXXX@" + t.split("@", 1)[1]
    if rule == "DATE_YEAR_MASK":
        s, t = _text(live)[:10], _text(true)[:10]
        return s[:4] == t[:4] and s[4:] == "-01-01"
    if rule == "DEFAULT_MASKING_VALUE":
        defaults = {"STRING": "", "INTEGER": 0, "FLOAT": 0.0, "NUMERIC": 0, "BOOLEAN": False, "DATE": "1970-01-01"}
        return col_type in defaults and _text(live) == _text(defaults[col_type]) and _text(live) != _text(true)
    raise ValueError(f"unknown masking rule {rule!r}")


def _same(a, b) -> bool:
    """Equal as stored: a TIMESTAMP is the same instant whatever the notation (`Z`, `+00:00`, microseconds)."""
    if a is None or b is None:
        return a is None and b is None
    x, y = _text(a), _text(b)
    if x == y:
        return True
    try:
        return datetime.fromisoformat(x.replace("Z", "+00:00")) == datetime.fromisoformat(y.replace("Z", "+00:00"))
    except ValueError:
        return False


def judge(transcript: dict, expected: dict, stored: list[dict], types: dict[str, str]) -> list[Finding]:
    """One seat's live transcript against the simulator's answer for the same query.

    `stored` is every row of the table as loaded (the synthetic data). A live row is matched to a stored row by the
    columns the seat sees in clear (a masked key cannot identify its own row): the candidates are the stored rows
    equal on every clear column, and the row is accepted only if some candidate also satisfies every masked column's
    rule. A query for which the seat sees no column in clear identifies nothing and is refused as such."""
    seat, table = transcript["seat"], transcript["table"]
    target = f"{table} as {seat}"
    out: list[Finding] = []

    def f(code: str, msg: str) -> None:
        out.append(Finding(code, "access", target, msg))

    if "error" in expected:
        if transcript["outcome"] != "error":
            f(
                "LIVE_ACCESS_ALLOWED",
                f"the compiled controls deny this seat ({expected['error']}); BigQuery returned rows",
            )
        return out
    if transcript["outcome"] == "error":
        f("LIVE_ACCESS_DENIED", f"the compiled controls allow this seat; BigQuery refused: {transcript['error'][:200]}")
        return out
    want = len(expected["rows"])
    got = len(transcript["rows"])
    if expected["rows_visible"] == 0 and got != 0:
        f("LIVE_ROWS", f"the row policies show this seat no rows; BigQuery returned {got}")
    elif expected["rows_visible"] > 0 and got != want:
        f("LIVE_ROWS", f"expected {want} row(s) (of {expected['rows_visible']} visible), BigQuery returned {got}")
    pred = expected.get("row_filter") or "TRUE"
    if pred != "TRUE":
        leaked = [row for row in transcript["rows"] if not _row_passes(pred, row)]
        if leaked:
            f("LIVE_ROW_POLICY", f"{len(leaked)} returned row(s) fail the compiled row access policy {pred}")
    clear = [c for c, r in expected["access"].items() if r == "clear"]
    masked = {c: r for c, r in expected["access"].items() if r != "clear"}
    visible = [b for b in stored if pred == "TRUE" or _row_passes(pred, b)]
    if transcript["rows"] and not clear:
        f("LIVE_VALUE_UNKNOWN", "no column is clear for this seat, so no live row can be tied to a stored row")
        return out
    for row in transcript["rows"]:
        candidates = [b for b in visible if all(_same(row.get(c), b.get(c)) for c in clear)]
        if not candidates:
            f("LIVE_VALUE_UNKNOWN", f"no stored row has the clear values { ({c: row.get(c) for c in clear})!r}")
            continue
        bad = {
            c: [b for b in candidates if not consistent(r, row.get(c), b.get(c), types.get(c, "STRING"))]
            for c, r in masked.items()
        }
        # a column fails only if it fails for every candidate; report each such column once per row
        for c, r in masked.items():
            if len(bad[c]) == len(candidates):
                f("LIVE_VALUE_NOT_MASKED", f"{c}: expected {r}, live value {row.get(c)!r} fits no stored row")
    return out
