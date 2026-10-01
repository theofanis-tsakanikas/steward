"""Claim 1 — value-based detection of personal data.

**The detector reads values only.** It never sees a contract, a column name, a schema type or the
planted ground truth: `detect()` takes {column: [values]} and the keys are carried, never read.
Comparing a detector that read the contract with the contract would be one function agreeing with
itself.

**One hit is enough** (doctrine 1: uncertainty resolves to sensitive). Over-tagging costs an analyst an
access request; under-tagging is a breach. The one exception is birth dates in a structured date
column — a column of `created_at` dates older than 16 years is history, not birthdays — which is
flagged only when the column as a whole looks like ages (see `_birth_column`).

Detectors (deterministic, value-shaped):
  msisdn      phone numbers — any E.164 number (+CC or 00CC, separators . - space ( ) allowed) and the
              national mobile formats of the three markets (GR 69…, IT 3…, DE 015/016/017…).
              A person's landline is personal data too, so "phone number" is the honest kind.
  imsi        15 digits starting with a European MCC (2xx) — Luhn is not consulted (1 in 10 passes by chance)
  imei        15 digits not starting with 2, optionally grouped (35-209900-176148-1), passing the Luhn check
  email       local@domain.tld
  iban        2 letters + 2 check digits + BBAN, any case, optionally grouped by spaces, mod-97 valid
  birth_date  a date 16–110 years before the scan date: ISO, D/M/Y with / . or -, Y/M/D, "12 March 1984"
              (EN/IT/DE month names); never the date part of a timestamp
  address     street-type words (GR in Latin and Greek script, IT, DE incl. "str.", EN) + a house number
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from .contract import DETECTABLE_KINDS as KINDS  # noqa: F401 — one vocabulary, shared with contracts

_E164 = re.compile(r"(?<![\w+])(?:\+|00)[ ]?\(?[1-9]\d{0,2}\)?(?:[ .\-]?\(?\d\)?){6,13}(?!\w)")
_NATIONAL = re.compile(r"(?<![\w+\d])(?:69\d(?:[ ]?\d){7}|3\d{2}(?:[ ]?\d){6,7}|01[5-7]\d(?:[ ]?\d){6,8})(?![\w\d])")
_DIGITS15 = re.compile(r"(?<![\d-])\d{2}[- ]?\d{6}[- ]?\d{6}[- ]?\d(?![\d-])")
_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")
_DATE_NUM = re.compile(
    r"(?<![\d.\-/])(?:(?P<y1>\d{4})[-/.](?P<m1>\d{1,2})[-/.](?P<d1>\d{1,2})|(?P<d2>\d{1,2})[-/.](?P<m2>\d{1,2})[-/.](?P<y2>\d{4}))(?![\d])(?!T\d)(?![ ]\d{2}:)"
)
_MONTHS = {
    **dict.fromkeys(["january", "jan", "gennaio", "januar"], 1),
    **dict.fromkeys(["february", "feb", "febbraio", "februar"], 2),
    **dict.fromkeys(["march", "mar", "marzo", "marz", "maerz"], 3),
    **dict.fromkeys(["april", "apr", "aprile"], 4),
    **dict.fromkeys(["may", "maggio", "mai"], 5),
    **dict.fromkeys(["june", "jun", "giugno", "juni"], 6),
    **dict.fromkeys(["july", "jul", "luglio", "juli"], 7),
    **dict.fromkeys(["august", "aug", "agosto"], 8),
    **dict.fromkeys(["september", "sep", "sept", "settembre"], 9),
    **dict.fromkeys(["october", "oct", "ottobre", "oktober", "okt"], 10),
    **dict.fromkeys(["november", "nov", "novembre"], 11),
    **dict.fromkeys(["december", "dec", "dicembre", "dezember", "dez"], 12),
}
_DATE_WORD = re.compile(r"(?i)\b(\d{1,2})\.?\s+([^\W\d_]{3,12})\.?,?\s+(\d{4})\b")
_DATE_WORD_MDY = re.compile(r"(?i)\b([^\W\d_]{3,12})\.?\s+(\d{1,2}),?\s+(\d{4})\b")
# Greek genitive month names (the form used in dates: "12 Μαρτίου 1984"), accents stripped before lookup
_MONTHS_EL = {"ιανουαριου": 1, "φεβρουαριου": 2, "μαρτιου": 3, "απριλιου": 4, "μαιου": 5, "ιουνιου": 6, "ιουλιου": 7,
              "αυγουστου": 8, "σεπτεμβριου": 9, "οκτωβριου": 10, "νοεμβριου": 11, "δεκεμβριου": 12}  # fmt: skip
_STREET = re.compile(
    r"(?i)(?:\b(?:odos|odou|leoforos|leof\.|plateia|via|viale|corso|piazza|vicolo|largo)\s+[^\W\d_][\w'\- ]{1,40}?,?\s+\d{1,4}\b"
    r"|(?:οδός|οδ\.|λεωφόρος|λεωφ\.|πλατεία)\s+[^\W\d_][\w'\- ]{1,40}?,?\s+\d{1,4}\b"
    r"|\b[^\W\d_][\w\-]*(?:strasse|straße|str\.|weg|allee|platz|gasse|ring|damm)\s*\d{1,4}\b"
    r"|\b[^\W\d_][\w\-]*\s+(?:strasse|straße|str\.|weg|allee|platz|gasse|ring|damm)\s*\d{1,4}\b"
    r"|\b\d{1,4}\s+[A-Za-z][A-Za-z ]{1,40}\s(?:street|road|avenue|lane|drive)\b)"
)


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
    s = s.replace(" ", "").upper()
    if not (15 <= len(s) <= 34):
        return False
    r = s[4:] + s[:4]
    try:
        return int("".join(str(int(c, 36)) for c in r)) % 97 == 1
    except ValueError:
        return False


_IBAN_START = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\d{2}")


def find_ibans(value: str) -> list[str]:
    """Every mod-97-valid IBAN in a value, written compact or grouped, any case. Grouped IBANs run
    into the next word ("…2300 695 or"), so each start is tried at every length and the longest
    valid prefix wins."""
    out = []
    for m in _IBAN_START.finditer(value):
        i, chars, ends = m.start(), [], []
        j = i
        while j < len(value) and len(chars) < 34:
            ch = value[j]
            if ch.isalnum() and ch.isascii():
                chars.append(ch)
                if len(chars) >= 15:
                    ends.append((len(chars), j + 1))
            elif not (ch == " " and j + 1 < len(value) and value[j + 1].isalnum() and chars):
                break
            j += 1
        for n, end in reversed(ends):
            if iban_ok("".join(chars[:n])):
                out.append(value[i:end])
                break
    return out


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _dates(value: str) -> list[date]:
    out = []
    for m in _DATE_NUM.finditer(value):
        if m.group("y1"):
            d = _safe_date(int(m.group("y1")), int(m.group("m1")), int(m.group("d1")))
        else:
            d = _safe_date(int(m.group("y2")), int(m.group("m2")), int(m.group("d2")))
        if d:
            out.append(d)
    for rx, day_g, mon_g in ((_DATE_WORD, 1, 2), (_DATE_WORD_MDY, 2, 1)):
        for m in rx.finditer(value):
            month = _month(m.group(mon_g))
            if month:
                d = _safe_date(int(m.group(3)), month, int(m.group(day_g)))
                if d:
                    out.append(d)
    return out


def _month(word: str) -> int | None:
    w = "".join(c for c in unicodedata.normalize("NFKD", word.lower()) if not unicodedata.combining(c))
    return _MONTHS.get(w) or _MONTHS_EL.get(w)


def _years_before(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year - years)
    except ValueError:  # 29 February → 28 February
        return d.replace(year=d.year - years, day=28)


def _window(scan_date: date) -> tuple[date, date]:
    return _years_before(scan_date, 110), _years_before(scan_date, 16)


# Placeholder dates legacy systems write for "unknown". They are neither births nor evidence against.
SENTINELS = frozenset(
    {date(1, 1, 1), date(1800, 1, 1), date(1899, 12, 31), date(1900, 1, 1), date(1970, 1, 1), date(9999, 12, 31)}
)


def scan_value(value: str, scan_date: date) -> dict[str, int]:
    """Kinds found in one value → count of matches. Pure, value only. Keys starting with `_` are
    signals the column-level decision uses, not kinds."""
    found: Counter[str] = Counter()
    ibans = find_ibans(value)
    found["iban"] = len(ibans)
    for ib in ibans:  # an IBAN's digit groups must not be read again as a phone number
        value = value.replace(ib, " ")
    phones = 0
    for m in _E164.finditer(value):
        digits = re.sub(r"\D", "", m.group(0))
        digits = digits[2:] if m.group(0).startswith("00") else digits
        if 8 <= len(digits) <= 15:
            phones += 1
    phones += len(_NATIONAL.findall(value))
    found["msisdn"] = phones
    for m in _DIGITS15.finditer(value):
        s = re.sub(r"\D", "", m.group(0))
        # A European MCC (2xx) leads an IMSI; one IMSI in ten passes Luhn by chance, so the prefix
        # decides first. Any other 15-digit number is an IMEI only if its Luhn digit is right.
        if s[0] == "2":
            found["imsi"] += 1
        elif luhn_ok(s):
            found["imei"] += 1
    found["email"] = len(_EMAIL.findall(value))
    lo, hi = _window(scan_date)
    ds = [d for d in _dates(value) if d not in SENTINELS]
    found["birth_date"] = sum(1 for d in ds if lo <= d <= hi)
    if ds and value.strip() and len(_DATE_NUM.sub("", value).strip()) == 0:
        found["_bare_date"] = 1
    found["address"] = len(_STREET.findall(value))
    return {k: v for k, v in found.items() if v}


@dataclass
class ColumnDetection:
    column: str
    n_values: int
    hits: dict[str, int] = field(default_factory=dict)  # kind -> number of values containing it
    kinds: list[str] = field(default_factory=list)  # kinds the column is flagged for

    def to_dict(self) -> dict:
        return {"column": self.column, "n_values": self.n_values, "hits": self.hits, "kinds": self.kinds}


def _birth_column(n: int, bare: int, births: int) -> bool:
    """A structured date column (≥80% of its non-sentinel values are bare dates) is a birth-date
    column if at least half of those dates fall in the 16–110-year window — minors and a few typos
    must not hide it; a column of recent `created` dates is not one. Free text and mixed columns:
    one in-window date is enough."""
    if n and bare >= 0.8 * n:
        return births >= 0.5 * bare
    return births >= 1


def detect_column(column: str, values: list, scan_date: date) -> ColumnDetection:
    vals = [str(v) for v in values if v is not None and str(v) != ""]
    per_kind: Counter[str] = Counter()
    n_sentinel = sum(
        1 for v in vals if (ds := _dates(v)) and all(d in SENTINELS for d in ds) and not _DATE_NUM.sub("", v).strip()
    )
    for v in vals:
        for k in scan_value(v, scan_date):
            per_kind[k] += 1
    bare = per_kind.pop("_bare_date", 0)
    kinds = sorted(k for k, c in per_kind.items() if c >= 1 and k != "birth_date")
    if per_kind.get("birth_date") and _birth_column(len(vals) - n_sentinel, bare, per_kind["birth_date"]):
        kinds = sorted([*kinds, "birth_date"])
    return ColumnDetection(column, len(vals), dict(sorted(per_kind.items())), kinds)


def detect(columns: dict[str, list], scan_date: date) -> list[ColumnDetection]:
    """{opaque column key: values} → detections. The keys are carried, never read."""
    return [detect_column(c, vals, scan_date) for c, vals in sorted(columns.items())]


# ── values out of nested rows ─────────────────────────────────────────────────────────────────────

UNSCHEMED = "__unschemed__"


def column_values(rows: list[dict], fields: list[dict], prefix: str = "") -> dict[str, list]:
    """Flatten nested/repeated rows into {path: [leaf values]} following a BigQuery schema.

    Nothing is dropped silently: a non-object value where the schema says RECORD is scanned at the
    RECORD's own path, and a key present in rows but absent from the schema is scanned under
    `<path>.__unschemed__.<key>` so a drifted field is still inspected (and later fails as undeclared).
    """
    out: dict[str, list] = {}

    def walk(objs: list, flds: list[dict], pre: str) -> None:
        names = {f["name"] for f in flds}
        for o in objs:
            if isinstance(o, dict):
                for k in o.keys() - names:
                    out.setdefault(f"{pre}{UNSCHEMED}.{k}", []).append(o[k])
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
                odd = [v for v in vals if v is not None and not isinstance(v, dict)]
                if odd:
                    out.setdefault(path, []).extend(odd)
                walk([v for v in vals if isinstance(v, dict)], f["fields"], path + ".")
            else:
                out.setdefault(path, []).extend(vals)

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
