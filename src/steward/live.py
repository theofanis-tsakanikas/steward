"""What the live captures ask, and the offline re-check of what they answered.

Outside `core/` (it reads the repository's files); every verdict is a core function. The capture side
(adapters/capture.py) calls GCP; this side never does, so CI can re-check committed evidence with no account.
"""

from __future__ import annotations

from dataclasses import dataclass

from steward import io, pipeline
from steward.core import access_live
from steward.core.findings import Finding
from steward.core.simulate import answer, model

LIMIT = 5


@dataclass(frozen=True)
class Query:
    id: str
    table: str
    columns: tuple[str, ...]
    order_by: tuple[str, ...]  # clear for every seat: ordering by a tagged column would need access to it
    where: str | None  # a table with require_partition_filter refuses a query without a predicate on the partition
    seats: tuple[str, ...]  # seat names as in infra/seats.json; "steward" = the dataset's steward seat

    def sql(self) -> str:
        from steward.adapters.gcp import select_sql

        return select_sql(self.table, self.columns, self.order_by, LIMIT, self.where)


QUERIES = (
    Query(
        "customers",
        "crm.customers",
        ("customer_id", "msisdn", "email", "birth_date", "country", "segment", "created_at"),
        ("created_at", "country"),
        None,
        ("analyst@GR", "steward", "fraud_investigator", "bi_service"),
    ),
    Query(
        "usage",
        "network.usage_events",
        ("event_id", "event_ts", "msisdn", "imsi", "country", "event_type"),
        ("event_id",),
        "event_date >= DATE '1970-01-01'",
        ("fraud_investigator", "steward", "analyst@GR", "bi_service"),
    ),
)
# A requester holding an approved, expiring marketplace grant (B46): the grant opens the dataset, the controls
# are compiled for seats, so the person gets no clear columns. Expected by the controls: denied.
PROBE_PERSON = "user:paolo.marino@halverra.example"


def steward_of(e, table: str) -> str:
    return next(c.steward for c in e.contracts if c.dataset == table.split(".")[0])


def resolve(e, q: Query, seat: str) -> str:
    return steward_of(e, q.table) if seat == "steward" else seat


def types_of(table: str) -> dict[str, str]:
    return {f["name"]: f["type"] for f in io.harvest()[table]["fields"]}


def expected_answer(e, am, q: Query, seat: str) -> dict:
    return answer(am, seat, q.table, list(q.columns), io.synthetic_rows(q.table), types_of(q.table), limit=LIMIT)


def verify_access(data: dict, e=None) -> list[Finding]:
    """Judge a captured access evidence document against the compiled controls and the stored data."""
    e = e or pipeline.load()
    am = model(e.compiled["infra/estate/generated.tf.json"], e.compiled["infra/governance/generated.tf.json"])
    by_id = {q.id: q for q in QUERIES}
    out: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for tr in data["transcripts"]:
        q = by_id.get(tr["query"])
        if q is None:
            out.append(Finding("LIVE_QUERY_UNKNOWN", "access", tr["query"], "a transcript of a query nobody declared"))
            continue
        seen.add((q.id, tr["seat"]))
        exp = expected_answer(e, am, q, tr["seat"])
        out += access_live.judge(tr, exp, io.synthetic_rows(q.table), types_of(q.table))
    for q in QUERIES:
        for s in q.seats:
            if (q.id, resolve(e, q, s)) not in seen:
                out.append(Finding("LIVE_TRANSCRIPT_MISSING", "access", f"{q.table} as {s}", "no transcript captured"))
    return out
