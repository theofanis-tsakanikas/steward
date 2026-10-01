"""Claim 1 — value-based detection of personal data, and the unclassified-PII gate.

**The detector reads values only.** It never sees a contract, a column name or the planted
manifest: `detect()` takes {column: [values]} and nothing else, and the column names in that dict are
opaque keys it does not inspect. Comparing a detector that read the contract with the contract would
be one function agreeing with itself.

Name-based heuristics live in `name_heuristics()`, are reported in a separate column, and never
count as proof of anything.

Detectors (all deterministic, all value-shaped):
  msisdn      E.164 mobile numbers for the three markets (+30 69…, +39 3…, +49 15/16/17…), also in the
              `00`-prefixed and space/dash-separated forms an old system prints
  imsi        15 digits whose first three are a European MCC (2xx) — told apart from IMEIs per column
  imei        15 digits with a valid Luhn check digit
  email       RFC-5322-ish local@domain.tld
  iban        country code + 2 check digits + BBAN, valid ISO 7064 mod-97
  birth_date  a calendar date 16–110 years before the scan date (ISO, DD/MM/YYYY, DD.MM.YYYY)
  address     street-type words of four languages followed by a house number (Odos, Via, …strasse, Street)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from .contract import DETECTABLE_KINDS as KINDS  # noqa: F401 — one vocabulary, shared with contracts

_PHONE = re.compile(r"(?<![\w+])(?:\+|00)\d[\d \-]{8,17}\d(?!\w)")
_MOBILE = re.compile(r"^\+(?:3069\d{8}|393\d{8,9}|491[5-7]\d{8,9})$")
_DIGITS15 = re.compile(r"(?<!\d)\d{15}(?!\d)")
_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")
_IBAN = re.compile(r"(?<![A-Z0-9])[A-Z]{2}\d{2}[A-Z0-9]{11,30}(?![A-Z0-9])")
_DATE = re.compile(r"(?<!\d)(?:(\d{4})-(\d{2})-(\d{2})|(\d{2})[/.](\d{2})[/.](\d{4}))(?![\d])")
_STREET = re.compile(
    r"(?i)(?:\b(?:odos|leoforos|plateia|via|viale|corso|piazza|vicolo)\s+[A-Za-zÀ-ÿ'\- ]{2,40}?\s+\d{1,4}\b"
    r"|\b[A-Za-zÀ-ÿ\-]+(?:strasse|straße|weg|allee|platz|gasse|ring)\s+\d{1,4}\b"
    r"|\b\d{1,4}\s+[A-Za-z][A-Za-z ]{1,40}\s(?:street|road|avenue|lane)\b)"
)

# A column is flagged for a kind when at least MIN_HITS values match AND they are at least
# MIN_SHARE of the non-null values. Low on purpose: uncertainty resolves to sensitive (doctrine 1),
# and over-tagging costs an access request while under-tagging is a breach.
MIN_HITS = 3
MIN_SHARE = 0.01


def luhn_ok(s: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(s)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iban_ok(s: str) -> bool:
    r = s[4:] + s[:4]
    try:
        return int("".join(str(int(c, 36)) for c in r)) % 97 == 1
    except ValueError:
        return False


def _to_date(m: re.Match) -> date | None:
    try:
        if m.group(1):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return date(int(m.group(6)), int(m.group(5)), int(m.group(4)))
    except ValueError:
        return None


def scan_value(value: str, scan_date: date) -> dict[str, int]:
    """Kinds found in one value → count of matches. Pure, value only."""
    found: Counter[str] = Counter()
    for m in _PHONE.finditer(value):
        num = re.sub(r"[ \-]", "", m.group(0))
        num = "+" + num[2:] if num.startswith("00") else num
        if _MOBILE.match(num):
            found["msisdn"] += 1
    for m in _DIGITS15.finditer(value):
        s = m.group(0)
        if luhn_ok(s):
            found["_luhn15"] += 1
        if s[0] == "2":
            found["_mcc15"] += 1
            if not luhn_ok(s):
                found["_mcc15_nonluhn"] += 1
        found["_d15"] += 1
    found["email"] += len(_EMAIL.findall(value))
    found["iban"] += sum(1 for m in _IBAN.finditer(value) if iban_ok(m.group(0)))
    lo, hi = scan_date.replace(year=scan_date.year - 110), scan_date.replace(year=scan_date.year - 16)
    for m in _DATE.finditer(value):
        d = _to_date(m)
        if d and lo <= d <= hi:
            found["birth_date"] += 1
    found["address"] += len(_STREET.findall(value))
    return {k: v for k, v in found.items() if v}


@dataclass
class ColumnDetection:
    column: str
    n_values: int
    hits: dict[str, int] = field(default_factory=dict)  # kind -> number of values containing it
    kinds: list[str] = field(default_factory=list)  # kinds the column is flagged for

    def to_dict(self) -> dict:
        return {"column": self.column, "n_values": self.n_values, "hits": self.hits, "kinds": self.kinds}


def detect_column(column: str, values: list, scan_date: date) -> ColumnDetection:
    vals = [str(v) for v in values if v is not None and str(v) != ""]
    per_kind: Counter[str] = Counter()
    for v in vals:
        for k in scan_value(v, scan_date):
            per_kind[k] += 1
    n = len(vals)
    # 15-digit identifiers: IMEIs carry a Luhn digit, IMSIs a European MCC. A Luhn digit happens by
    # chance on ~10% of random numbers, so the column, not the value, decides.
    d15 = per_kind.pop("_d15", 0)
    luhn15 = per_kind.pop("_luhn15", 0)
    mcc_nonluhn = per_kind.pop("_mcc15_nonluhn", 0)
    per_kind.pop("_mcc15", 0)
    if d15 and luhn15 >= 0.5 * d15:
        per_kind["imei"] = luhn15
    elif d15 and mcc_nonluhn:
        per_kind["imsi"] = mcc_nonluhn
    need = max(MIN_HITS, math.ceil(MIN_SHARE * n))
    kinds = sorted(k for k, c in per_kind.items() if c >= need)
    return ColumnDetection(column, n, dict(sorted(per_kind.items())), kinds)


def detect(columns: dict[str, list], scan_date: date) -> list[ColumnDetection]:
    """{opaque column key: values} → detections. The keys are carried, never read."""
    return [detect_column(c, vals, scan_date) for c, vals in sorted(columns.items())]


# ── values out of nested rows ─────────────────────────────────────────────────────────────────────


def column_values(rows: list[dict], fields: list[dict], prefix: str = "") -> dict[str, list]:
    """Flatten nested/repeated rows into {path: [leaf values]} following a BigQuery schema."""
    out: dict[str, list] = {}

    def walk(objs: list, flds: list[dict], pre: str) -> None:
        for f in flds:
            path = pre + f["name"]
            vals = []
            for o in objs:
                if not isinstance(o, dict):
                    continue
                v = o.get(f["name"])
                if isinstance(v, list):
                    vals.extend(v)
                else:
                    vals.append(v)
            if f.get("fields"):
                walk([v for v in vals if isinstance(v, dict)], f["fields"], path + ".")
            else:
                out[path] = vals

    walk(rows, fields, prefix)
    return out


# ── name heuristics: reported, never proof ────────────────────────────────────────────────────────

_NAME_HINTS = {
    "msisdn": r"msisdn|phone|mobile|tel|callback",
    "imsi": r"imsi",
    "imei": r"imei",
    "email": r"e?mail",
    "iban": r"iban|bank|account_no",
    "birth_date": r"birth|dob",
    "address": r"address|street|addr",
}


def name_heuristics(column_path: str) -> list[str]:
    leaf = column_path.split(".")[-1].lower()
    return sorted(k for k, rx in _NAME_HINTS.items() if re.search(rx, leaf))
