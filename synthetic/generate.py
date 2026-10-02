#!/usr/bin/env python3
"""The fictional operator's data — Halverra Telecom, seeded and deterministic.

Writes, under synthetic/data/:
  <dataset>.<table>.jsonl   newline-delimited JSON, the format BigQuery loads (nested + repeated)
  _schema.json              the BigQuery schema of every table (what INFORMATION_SCHEMA would say)
and evals/ground_truth/planted.json: the ground truth of where personal data and quality defects were
planted. It lives under evals/ so that nothing shipped from src/ sits next to it; a runtime audit hook
(tests/test_planted_isolation.py) fails if the detector, gates or compiler ever open it.

Everything here is invented. Names come from short lists of common given names and surnames;
e-mail domains are the reserved `example.*` domains (RFC 2606); IBANs carry valid check digits over
invented bank codes; MSISDNs, IMSIs and IMEIs are random numbers in the right *shape*. No row
describes a real person and nothing links a generated number to anyone who might hold it.

    python synthetic/generate.py            # write
    python synthetic/generate.py --check    # regenerate in memory, fail if anything differs
    python synthetic/generate.py --out DIR  # write somewhere else (the determinism test uses this)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PLANTED = "evals/ground_truth/planted.json"  # relative to the repository root
SEED = 20261001
ANCHOR = date(2026, 9, 30)  # "today" for the generator — fixed, so output never depends on the clock
COUNTRIES = ("GR", "IT", "DE")

SIZES = {
    "customers": 600,
    "support_tickets": 400,
    "usage_events": 6000,
    "network_events": 3000,
    "billing": 1800,
    "legacy_crm_export": 150,
}

FIRST = {
    "GR": ["Eleni", "Giorgos", "Maria", "Nikos", "Katerina", "Dimitris", "Sofia", "Kostas", "Anna", "Yannis"],
    "IT": ["Giulia", "Marco", "Chiara", "Luca", "Francesca", "Matteo", "Sara", "Andrea", "Elena", "Paolo"],
    "DE": ["Lena", "Jonas", "Mia", "Felix", "Hannah", "Lukas", "Laura", "Paul", "Julia", "Max"],
}
LAST = {
    "GR": ["Papadopoulou", "Georgiou", "Nikolaou", "Ioannou", "Vasileiou", "Christou", "Antoniou", "Pappas"],
    "IT": ["Rossi", "Bianchi", "Romano", "Colombo", "Ricci", "Marino", "Greco", "Bruno"],
    "DE": ["Mueller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker"],
}
STREETS = {
    "GR": ["Odos Ermou", "Odos Athinas", "Odos Patision", "Leoforos Kifisias", "Odos Egnatias"],
    "IT": ["Via Roma", "Via Garibaldi", "Via Mazzini", "Corso Italia", "Via Verdi"],
    "DE": ["Hauptstrasse", "Bahnhofstrasse", "Gartenweg", "Schulstrasse", "Lindenallee"],
}
CITIES = {
    "GR": ["Athina", "Thessaloniki", "Patra", "Irakleio"],
    "IT": ["Milano", "Torino", "Bologna", "Napoli"],
    "DE": ["Berlin", "Hamburg", "Koeln", "Leipzig"],
}
CITY_CODE = {"Athina": "ATH", "Thessaloniki": "SKG", "Patra": "PAT", "Irakleio": "HER", "Milano": "MIL",
             "Torino": "TRN", "Bologna": "BLQ", "Napoli": "NAP", "Berlin": "BER", "Hamburg": "HAM",
             "Koeln": "CGN", "Leipzig": "LEJ"}  # fmt: skip
MAIL_DOMAINS = ["example.com", "example.org", "example.net"]
PLANS = ["Halverra Go", "Halverra Plus", "Halverra Max", "Halverra Home Fibre", "Halverra Business"]
# Mobile Country Codes are per country (ITU E.212). The MNCs here are chosen from the high end of
# the range so they are unlikely to name a real network; they are not claimed to be unassigned.
MCC_MNC = {"GR": "20297", "IT": "22297", "DE": "26297"}
MSISDN_PREFIX = {"GR": "+3069", "IT": "+393", "DE": "+4915"}
MSISDN_REST = {"GR": 8, "IT": 9, "DE": 9}


# ── identifiers with real check digits ────────────────────────────────────────────────────────────


def luhn_digit(body: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def iban(rng: random.Random, country: str) -> str:
    if country == "GR":
        bban = f"{rng.randint(900, 999):03d}{rng.randint(0, 9999):04d}{rng.randint(0, 10**16 - 1):016d}"
    elif country == "IT":
        bban = f"{rng.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{rng.randint(90000, 99999):05d}{rng.randint(0, 99999):05d}{rng.randint(0, 10**12 - 1):012d}"
    else:
        bban = f"{rng.randint(90000000, 99999999):08d}{rng.randint(0, 10**10 - 1):010d}"
    numeric = "".join(str(int(c, 36)) for c in bban + country + "00")
    check = 98 - int(numeric) % 97
    return f"{country}{check:02d}{bban}"


def msisdn(rng: random.Random, country: str) -> str:
    return MSISDN_PREFIX[country] + "".join(str(rng.randint(0, 9)) for _ in range(MSISDN_REST[country]))


def imsi(rng: random.Random, country: str) -> str:
    return MCC_MNC[country] + f"{rng.randint(0, 10**10 - 1):010d}"


def imei(rng: random.Random) -> str:
    body = rng.choice(["35", "86", "01", "49"]) + f"{rng.randint(0, 10**12 - 1):012d}"
    return body + luhn_digit(body)


def ts(d: date, rng: random.Random) -> str:
    t = datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(seconds=rng.randint(0, 86399))
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── the schema (what BigQuery's INFORMATION_SCHEMA would report) ─────────────────────────────────


def f(name: str, typ: str, mode: str = "NULLABLE", fields: list | None = None) -> dict:
    out = {"name": name, "type": typ, "mode": mode}
    if fields:
        out["fields"] = fields
    return out


SCHEMA: dict[str, dict] = {
    "crm.customers": {
        "partition": None,
        "fields": [
            f("customer_id", "STRING", "REQUIRED"),
            f("full_name", "STRING"),
            f("email", "STRING"),
            f("msisdn", "STRING"),
            f("birth_date", "DATE"),
            f("address", "RECORD", fields=[f("street", "STRING"), f("city", "STRING"), f("postcode", "STRING")]),
            f("country", "STRING", "REQUIRED"),
            f("segment", "STRING"),
            f(
                "consent",
                "RECORD",
                fields=[f("marketing", "BOOLEAN"), f("profiling", "BOOLEAN"), f("updated_at", "TIMESTAMP")],
            ),
            f(
                "contracts",
                "RECORD",
                "REPEATED",
                fields=[
                    f("contract_id", "STRING"),
                    f("plan", "STRING"),
                    f("start_date", "DATE"),
                    f("end_date", "DATE"),
                    f("status", "STRING"),
                    f("monthly_fee", "NUMERIC"),
                ],
            ),
            f("created_at", "TIMESTAMP"),
        ],
    },
    "crm.support_tickets": {
        "partition": None,
        "fields": [
            f("ticket_id", "STRING", "REQUIRED"),
            f("customer_id", "STRING"),
            f("opened_at", "TIMESTAMP"),
            f("channel", "STRING"),
            f("category", "STRING"),
            f("notes_free_text", "STRING"),
            f("ref_2", "STRING"),
            f("country", "STRING"),
            f("status", "STRING"),
        ],
    },
    "network.usage_events": {
        "partition": "event_date",
        "cluster": [
            "country",
            "event_type",
        ],  # never a tagged column: BigQuery cannot mask one (MASKED_COLUMN_CLUSTERED)
        "fields": [
            f("event_id", "STRING", "REQUIRED"),
            f("event_date", "DATE", "REQUIRED"),
            f("event_ts", "TIMESTAMP"),
            f("msisdn", "STRING"),
            f("imsi", "STRING"),
            f("cell_id", "STRING"),
            f("country", "STRING"),
            f("event_type", "STRING"),
            f("volume_mb", "FLOAT"),
            f("duration_s", "INTEGER"),
        ],
    },
    "network.network_events": {
        "partition": "event_date",
        "cluster": ["country", "rat"],
        "fields": [
            f("attach_id", "STRING", "REQUIRED"),
            f("event_date", "DATE", "REQUIRED"),
            f("ts", "TIMESTAMP"),
            f("imei", "STRING"),
            f("imsi", "STRING"),
            f("cell_id", "STRING"),
            f("country", "STRING"),
            f("rat", "STRING"),
        ],
    },
    "finance.billing": {
        "partition": "issue_date",
        "fields": [
            f("invoice_id", "STRING", "REQUIRED"),
            f("customer_id", "STRING"),
            f("iban", "STRING"),
            f("amount", "NUMERIC"),
            f("currency", "STRING"),
            f("issue_date", "DATE", "REQUIRED"),
            f("due_date", "DATE"),
            f("status", "STRING"),
            f("country", "STRING"),
        ],
    },
    "analytics.weekly_usage_by_cell": {
        "partition": "week_start",
        "cluster": ["country", "cell_id"],
        "fields": [
            f("week_start", "DATE", "REQUIRED"),
            f("country", "STRING", "REQUIRED"),
            f("cell_id", "STRING", "REQUIRED"),
            f("events", "INTEGER"),
            f("total_mb", "FLOAT"),
            f("subscribers", "INTEGER"),
        ],
    },
    "legacy.legacy_crm_export": {
        "partition": None,
        "fields": [
            f("k_id", "STRING"),
            f("nm_1", "STRING"),
            f("tel_a", "STRING"),
            f("fld_7", "STRING"),
            f("dt_x", "STRING"),
            f("adr_l1", "STRING"),
            f("cd_s", "STRING"),
            f("upd", "STRING"),
        ],
    },
}


# ── the generator ─────────────────────────────────────────────────────────────────────────────────


class Planted:
    """Ground truth. Written beside the data, read only by evals."""

    def __init__(self) -> None:
        self.pii: dict[str, set[str]] = {}
        self.innocent: set[str] = set()
        self.quality: list[dict] = []

    def mark(self, column: str, kind: str, innocent: bool = False) -> None:
        self.pii.setdefault(column, set()).add(kind)
        if innocent:
            self.innocent.add(column)

    def defect(self, table: str, offset: int, key: str, kind: str, column: str, note: str) -> None:
        self.quality.append(
            {"table": table, "offset": offset, "key": key, "kind": kind, "column": column, "note": note}
        )

    def to_json(self) -> dict:
        return {
            "_read_by": "evals only — no detector, compiler or gate may read this file",
            "seed": SEED,
            "anchor_date": ANCHOR.isoformat(),
            "pii": [
                {"column": c, "kinds": sorted(k), "planted_in_innocent_column": c in self.innocent}
                for c, k in sorted(self.pii.items())
            ],
            "quality_defects": sorted(self.quality, key=lambda d: (d["table"], d["offset"], d["kind"])),
        }


def gen_customers(rng: random.Random, planted: Planted) -> list[dict]:
    rows = []
    for i in range(SIZES["customers"]):
        c = COUNTRIES[i % 3]
        first, last = rng.choice(FIRST[c]), rng.choice(LAST[c])
        city = rng.choice(CITIES[c])
        birth = ANCHOR - timedelta(days=rng.randint(18 * 365 + 5, 85 * 365))
        contracts = []
        for j in range(rng.choice([1, 1, 1, 2, 2, 3])):
            start = ANCHOR - timedelta(days=rng.randint(30, 9 * 365))
            ended = rng.random() < 0.3
            end = start + timedelta(days=rng.choice([365, 730])) if ended else None
            contracts.append(
                {
                    "contract_id": f"K{i + 1:06d}-{j + 1}",
                    "plan": rng.choice(PLANS),
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat() if end else None,
                    "status": "ended" if ended else "active",
                    "monthly_fee": f"{rng.choice([9.9, 14.9, 19.9, 29.9, 39.9, 49.9]):.2f}",
                }
            )
        rows.append(
            {
                "customer_id": f"C{i + 1:06d}",
                "full_name": f"{first} {last}",
                "email": f"{first.lower()}.{last.lower()}{rng.randint(1, 999)}@{rng.choice(MAIL_DOMAINS)}",
                "msisdn": msisdn(rng, c),
                "birth_date": birth.isoformat(),
                "address": {
                    "street": f"{rng.choice(STREETS[c])} {rng.randint(1, 180)}",
                    "city": city,
                    "postcode": f"{rng.randint(10000, 99999)}",
                },
                "country": c,
                "segment": rng.choice(["consumer", "consumer", "business", "prepaid"]),
                "consent": {
                    "marketing": rng.random() < 0.45,
                    "profiling": rng.random() < 0.25,
                    "updated_at": ts(ANCHOR - timedelta(days=rng.randint(1, 700)), rng),
                },
                "contracts": contracts,
                "created_at": ts(ANCHOR - timedelta(days=rng.randint(30, 9 * 365)), rng),
            }
        )
    for col, kind in [
        ("crm.customers.email", "email"),
        ("crm.customers.msisdn", "msisdn"),
        ("crm.customers.birth_date", "birth_date"),
        ("crm.customers.address.street", "address"),
    ]:
        planted.mark(col, kind)
    return rows


NOTES_PLAIN = [
    "Customer reports slow data speeds in the evening; advised to restart the router.",
    "Roaming bundle not applied after border crossing; credited one day.",
    "Asked about upgrading to fibre; sent the offer by post.",
    "Complaint about a dropped call during a meeting; logged for network team.",
    "Bill higher than expected; explained the out-of-bundle charges.",
    "Requested a paper invoice instead of electronic delivery.",
    "SIM swap completed in store after identity check.",
    "Escalated on 2026-09-12 to second line, no further action needed.",
]


def gen_tickets(rng: random.Random, customers: list[dict], planted: Planted) -> list[dict]:
    rows = []
    for i in range(SIZES["support_tickets"]):
        cust = rng.choice(customers)
        c = cust["country"]
        note = rng.choice(NOTES_PLAIN)
        roll = rng.random()
        # ~22% of notes carry personal data an agent typed in — the leak no column name announces.
        if roll < 0.06:
            note += f" Call back on {msisdn(rng, c)} after 18:00."
        elif roll < 0.11:
            note += f" Confirmation sent to {cust['email']}."
        elif roll < 0.16:
            note += f" Identity confirmed with DOB {cust['birth_date']}."
        elif roll < 0.22:
            note += f" Refund to be paid to {iban(rng, c)}."
        # ref_2 was meant for an internal reference; agents used it for the callback number.
        ref2 = msisdn(rng, c) if rng.random() < 0.8 else f"REF-{rng.randint(10000, 99999)}"
        rows.append(
            {
                "ticket_id": f"T{i + 1:07d}",
                "customer_id": cust["customer_id"],
                "opened_at": ts(ANCHOR - timedelta(days=rng.randint(0, 365)), rng),
                "channel": rng.choice(["phone", "chat", "store", "email"]),
                "category": rng.choice(["network", "billing", "device", "contract"]),
                "notes_free_text": note,
                "ref_2": ref2,
                "country": c,
                "status": rng.choice(["open", "closed", "closed", "closed"]),
            }
        )
    for kind in ("msisdn", "email", "birth_date", "iban"):
        planted.mark("crm.support_tickets.notes_free_text", kind, innocent=True)
    planted.mark("crm.support_tickets.ref_2", "msisdn", innocent=True)
    return rows


def cells(rng: random.Random) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in COUNTRIES:
        out[c] = [f"{c}-{CITY_CODE[city]}-{rng.randint(1, 400):04d}" for city in CITIES[c] for _ in range(6)]
    return out


def gen_usage(rng: random.Random, customers: list[dict], cellmap: dict, planted: Planted) -> list[dict]:
    rows = []
    imsi_of = {cu["customer_id"]: imsi(rng, cu["country"]) for cu in customers}
    table = "network.usage_events"
    bad_type = set(rng.sample(range(SIZES["usage_events"]), 4))
    null_msisdn = set(rng.sample(sorted(set(range(SIZES["usage_events"])) - bad_type), 3))
    for i in range(SIZES["usage_events"]):
        cu = rng.choice(customers)
        d = ANCHOR - timedelta(days=rng.randint(1, 60))
        et = rng.choice(["voice", "sms", "data", "data", "data"])
        row = {
            "event_id": f"E{i + 1:08d}",
            "event_date": d.isoformat(),
            "event_ts": ts(d, rng),
            "msisdn": cu["msisdn"],
            "imsi": imsi_of[cu["customer_id"]],
            "cell_id": rng.choice(cellmap[cu["country"]]),
            "country": cu["country"],
            "event_type": et,
            "volume_mb": round(rng.uniform(0.1, 900.0), 2) if et == "data" else 0.0,
            "duration_s": rng.randint(5, 3600) if et == "voice" else 0,
        }
        if i in bad_type:
            row["event_type"] = "unknwn"
            planted.defect(table, i, row["event_id"], "validity", "event_type", "event_type outside the allowed set")
        if i in null_msisdn:
            row["msisdn"] = None
            planted.defect(table, i, row["event_id"], "completeness", "msisdn", "msisdn missing")
        rows.append(row)
    planted.mark("network.usage_events.msisdn", "msisdn")
    planted.mark("network.usage_events.imsi", "imsi")
    return rows


def gen_network(rng: random.Random, customers: list[dict], cellmap: dict, planted: Planted) -> list[dict]:
    rows = []
    for i in range(SIZES["network_events"]):
        cu = rng.choice(customers)
        d = ANCHOR - timedelta(days=rng.randint(1, 30))
        rows.append(
            {
                "attach_id": f"A{i + 1:08d}",
                "event_date": d.isoformat(),
                "ts": ts(d, rng),
                "imei": imei(rng),
                "imsi": imsi(rng, cu["country"]),
                "cell_id": rng.choice(cellmap[cu["country"]]),
                "country": cu["country"],
                "rat": rng.choice(["4G", "5G", "5G"]),
            }
        )
    planted.mark("network.network_events.imei", "imei")
    planted.mark("network.network_events.imsi", "imsi")
    return rows


def gen_billing(rng: random.Random, customers: list[dict], planted: Planted) -> list[dict]:
    table = "finance.billing"
    rows = []
    iban_of = {cu["customer_id"]: iban(rng, cu["country"]) for cu in customers}
    n = SIZES["billing"]
    negative = set(rng.sample(range(n), 3))
    orphan = set(rng.sample(sorted(set(range(n)) - negative), 2))
    for i in range(n):
        cu = customers[i % len(customers)]
        issue = ANCHOR - timedelta(days=30 * (i // len(customers)) + rng.randint(1, 28))
        row = {
            "invoice_id": f"INV-{issue.year}-{i + 1:06d}",
            "customer_id": cu["customer_id"],
            "iban": iban_of[cu["customer_id"]],
            "amount": f"{rng.uniform(9.9, 180.0):.2f}",
            "currency": "EUR",
            "issue_date": issue.isoformat(),
            "due_date": (issue + timedelta(days=20)).isoformat(),
            "status": rng.choice(["paid", "paid", "paid", "open", "overdue"]),
            "country": cu["country"],
        }
        if i in negative:
            row["amount"] = f"-{row['amount']}"
            planted.defect(table, i, row["invoice_id"], "validity", "amount", "negative invoice amount")
        if i in orphan:
            row["customer_id"] = f"C9{rng.randint(10000, 99999)}"
            planted.defect(
                table, i, row["invoice_id"], "referential", "customer_id", "customer_id not in crm.customers"
            )
        rows.append(row)
    # two duplicate invoices: an exact re-send of an earlier row, appended at the end
    for src in sorted(rng.sample(sorted(set(range(n)) - negative - orphan), 2)):
        dup = dict(rows[src])
        rows.append(dup)
        planted.defect(
            table, len(rows) - 1, dup["invoice_id"], "uniqueness", "invoice_id", f"duplicate of offset {src}"
        )
    planted.mark("finance.billing.iban", "iban")
    return rows


def gen_legacy(rng: random.Random, planted: Planted) -> list[dict]:
    """An export from a CRM retired in 2019. Nobody remembers what the columns mean."""
    rows = []
    for i in range(SIZES["legacy_crm_export"]):
        c = COUNTRIES[i % 3]
        num = msisdn(rng, c)
        # national format with spaces, the way the old system printed it: "0030 69x xxx xxxx"
        spaced = "00" + num[1:3] + " " + num[3:6] + " " + num[6:9] + " " + num[9:]
        birth = ANCHOR - timedelta(days=rng.randint(25 * 365, 80 * 365))
        rows.append(
            {
                "k_id": f"L{rng.randint(100000, 999999)}",
                "nm_1": f"{rng.choice(LAST[c]).upper()}, {rng.choice(FIRST[c])}",
                "tel_a": spaced,
                "fld_7": iban(rng, c),
                "dt_x": birth.strftime("%d/%m/%Y"),
                "adr_l1": f"{rng.choice(STREETS[c])} {rng.randint(1, 180)}",
                "cd_s": rng.choice(["A", "A", "S", "X"]),
                "upd": (date(2019, 1, 1) - timedelta(days=rng.randint(0, 900))).isoformat(),
            }
        )
    for col, kind in [("tel_a", "msisdn"), ("fld_7", "iban"), ("dt_x", "birth_date"), ("adr_l1", "address")]:
        planted.mark(f"legacy.legacy_crm_export.{col}", kind, innocent=True)
    return rows


K_ANONYMITY = 5  # a cell-week is published only if at least this many distinct subscribers used it


def gen_weekly_usage(usage: list[dict]) -> list[dict]:
    """The CTAS an analytics job runs over network.usage_events: per ISO week, country and cell —
    events, volume and distinct subscribers — keeping only groups with >= K_ANONYMITY subscribers.
    Derived, not sampled: the lineage edge usage_events → weekly_usage_by_cell is real."""
    groups: dict[tuple, dict] = {}
    for r in usage:
        if r["msisdn"] is None or r["event_type"] not in ("voice", "sms", "data"):
            continue  # the load quarantines these rows; the aggregate reads only loaded rows
        d = date.fromisoformat(r["event_date"])
        week = (d - timedelta(days=d.weekday())).isoformat()
        g = groups.setdefault((week, r["country"], r["cell_id"]), {"events": 0, "mb": 0.0, "subs": set()})
        g["events"] += 1
        g["mb"] += r["volume_mb"]
        g["subs"].add(r["msisdn"])
    return [
        {
            "week_start": w,
            "country": c,
            "cell_id": cell,
            "events": g["events"],
            "total_mb": round(g["mb"], 2),
            "subscribers": len(g["subs"]),
        }
        for (w, c, cell), g in sorted(groups.items())
        if len(g["subs"]) >= K_ANONYMITY
    ]


def build() -> dict[str, str]:
    """Return {relative path: file content}. Pure: same seed, same bytes."""
    rng = random.Random(SEED)
    planted = Planted()
    customers = gen_customers(rng, planted)
    cellmap = cells(rng)
    tickets = gen_tickets(rng, customers, planted)  # order matters: every table draws from one seeded RNG
    usage = gen_usage(rng, customers, cellmap, planted)
    tables = {
        "crm.customers": customers,
        "crm.support_tickets": tickets,
        "network.usage_events": usage,
        "network.network_events": gen_network(rng, customers, cellmap, planted),
        "finance.billing": gen_billing(rng, customers, planted),
        "legacy.legacy_crm_export": gen_legacy(rng, planted),
        "analytics.weekly_usage_by_cell": gen_weekly_usage(usage),
    }
    out: dict[str, str] = {}
    for name, rows in tables.items():
        out[f"data/{name}.jsonl"] = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows)
    schema = {name: {**spec, "row_count": len(tables[name])} for name, spec in SCHEMA.items()}
    out["data/_schema.json"] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    digests = {p: hashlib.sha256(c.encode()).hexdigest() for p, c in sorted(out.items())}
    out["data/_digests.json"] = json.dumps(digests, indent=2) + "\n"
    out["data/_meta.json"] = (
        json.dumps({"seed": SEED, "anchor_date": ANCHOR.isoformat(), "generator": "synthetic/generate.py"}, indent=2)
        + "\n"
    )
    out[PLANTED] = json.dumps(planted.to_json(), indent=2) + "\n"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if committed output differs")
    ap.add_argument("--out", type=Path, default=None, help="write data/ and the ground truth under DIR instead")
    args = ap.parse_args(argv)
    files = build()
    stale = []
    for rel, content in files.items():
        root = args.out if args.out is not None else (REPO if rel == PLANTED else HERE)
        path = root / rel
        if args.check:
            if not path.exists() or path.read_text() != content:
                stale.append(rel)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    if stale:
        print("SYNTHETIC_STALE " + " ".join(stale))
        return 1
    rows = {k: v.count("\n") for k, v in files.items() if k.endswith(".jsonl")}
    print(f"ok synthetic{' --check' if args.check else ''}: " + ", ".join(f"{k[5:-6]}={v}" for k, v in rows.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
