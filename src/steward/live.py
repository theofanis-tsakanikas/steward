"""What the live captures ask, and the offline re-check of what they answered.

Outside `core/` (it reads the repository's files); every verdict is a core function. The capture side
(adapters/capture.py) calls GCP; this side never does, so CI can re-check committed evidence with no account.
"""

from __future__ import annotations

from dataclasses import dataclass

from steward import io, pipeline
from steward.core import access_live, live_assurance
from steward.core.findings import Finding
from steward.core.marketplace import decide, gate, load_ledger
from steward.core.simulate import answer, model

LIMIT = 5

# Declared here so the capture and the judge share one string (LIVE_AUDIT_SQL fires if they drift).
ACCESS_REVIEW_SQL = """
SELECT
  protopayload_auditlog.authenticationInfo.principalEmail AS principal,
  protopayload_auditlog.methodName AS method,
  COUNT(*) AS events,
  MIN(timestamp) AS first_seen,
  MAX(timestamp) AS last_seen
FROM `audit.cloudaudit_googleapis_com_data_access`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 DAY)
  AND protopayload_auditlog.methodName IN ('google.cloud.bigquery.v2.JobService.InsertJob', 'jobservice.jobcompleted')
GROUP BY principal, method
ORDER BY principal, method
""".strip()

# BigQuery's default dataset ACL, the deployer who created the dataset (redacted), and the logging
# sink writer on `audit`. Anything else is a grant nobody approved (DECISIONS B55).
_DEFAULT_ACL = {
    ("specialGroup:projectOwners", "roles/bigquery.dataOwner"),
    ("specialGroup:projectReaders", "roles/bigquery.dataViewer"),
    ("specialGroup:projectWriters", "roles/bigquery.dataEditor"),
    ("serviceAccount:<service-account>", "roles/bigquery.dataOwner"),
}


def _iam_explained(m: dict) -> bool:
    if (m["member"], m["role"]) in _DEFAULT_ACL:
        return True
    return (
        m["dataset"] == "audit"
        and m["role"] == "roles/bigquery.dataEditor"
        and str(m["member"]).endswith("@gcp-sa-logging.iam.gserviceaccount.com")
    )


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


def verify_iam(data: dict, e=None) -> list[Finding]:
    """Judge a captured dataset-IAM snapshot against the marketplace ledger (claim 6), at the capture time."""
    e = e or pipeline.load()
    ledger, lf = load_ledger(e.ledger)
    if ledger is None:
        return lf
    out = gate(data, decide(ledger, e.contracts, e.roles), e.contracts, e.roles)
    for m in data.get("other_members", []):
        if _iam_explained(m):
            continue
        out.append(
            Finding(
                "LIVE_IAM_UNKNOWN_MEMBER",
                "iam",
                f"{m['dataset']} {m['member']}",
                f"{m['role']} held by a principal that is neither a seat nor a requester and not a documented default",
            )
        )
    return out


def verify_audit(data: dict, e=None) -> list[Finding]:
    if data.get("outcome") == "error":
        return [Finding("LIVE_AUDIT_ERROR", "audit", "access review", str(data.get("error", "no message"))[:200])]
    out: list[Finding] = []
    if data.get("sql") != ACCESS_REVIEW_SQL:
        out.append(
            Finding(
                "LIVE_AUDIT_SQL", "audit", "access review", "the capture did not run the declared access-review query"
            )
        )
    if not data.get("rows"):
        out.append(Finding("LIVE_AUDIT_EMPTY", "audit", "access review", "the sink answered no events"))
    principals = {r.get("principal") for r in data.get("rows", [])}
    if PROBE_PERSON not in principals:
        out.append(
            Finding(
                "LIVE_AUDIT_GRANTEE_MISSING",
                "audit",
                PROBE_PERSON,
                "the approved requester left no trail in the sink",
            )
        )
    return out


def verify_dlp(data: dict, e=None) -> list[Finding]:
    e = e or pipeline.load()
    return live_assurance.verify_dlp(data, e.compiled_tags, set(e.harvest))


def verify_dataplex(data: dict, e=None) -> list[Finding]:
    """Dataplex's per-rule failed rows vs the offline quality engine's quarantine (the committed fixture result)."""
    import json

    quality = json.loads((io.REPO / "evidence" / "fixture" / "quality.json").read_text())["data"]
    counts = {t: c["source"] for t, c in quality["counts"].items()}
    e = e or pipeline.load()
    scans = e.compiled["infra/assurance/generated.tf.json"]["resource"]["google_dataplex_datascan"]
    compiled = {r["name"] for s in scans.values() for r in s["data_quality_spec"]["rules"]}
    return live_assurance.verify_dataplex(data, counts, quality["by_rule"], compiled)


def verify_history(data: dict, e=None) -> list[Finding]:
    e = e or pipeline.load()
    return live_assurance.verify_history(data, set(e.harvest))


VERIFY = {
    "access": verify_access,
    "iam": verify_iam,
    "dlp": verify_dlp,
    "dataplex": verify_dataplex,
    "audit": verify_audit,
    "history": verify_history,
}
