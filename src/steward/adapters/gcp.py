"""The thin layer over Google's client libraries: credentials, an authorised REST session, a capped BigQuery query.

No decision is made here. Every query goes through `run_query`, which sets `maximum_bytes_billed` (CLAUDE.md cost
controls) - there is no other way in this package to start a BigQuery job. Needs the `gcp` extra and credentials
(Application Default Credentials; in CI, the deployer service account by Workload Identity Federation).
"""

from __future__ import annotations

import base64
import datetime as dt
import decimal
from collections.abc import Sequence

SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
LOCATION = "EU"
MAX_BYTES_BILLED = 100 * 1024 * 1024  # 100 MiB: the whole synthetic estate is ~3 MB


def credentials(impersonate: str | None = None):
    """ADC, or ADC acting as `impersonate` (a seat's service account; needs serviceAccountTokenCreator)."""
    import google.auth
    from google.auth import impersonated_credentials

    base, _ = google.auth.default(scopes=list(SCOPES))
    if not impersonate:
        return base
    return impersonated_credentials.Credentials(
        source_credentials=base, target_principal=impersonate, target_scopes=list(SCOPES), lifetime=600
    )


def session(creds):
    from google.auth.transport.requests import AuthorizedSession

    return AuthorizedSession(creds)


def plain(v):
    """A BigQuery value as JSON: dates and timestamps as ISO text, bytes as base64, NUMERIC as a number."""
    if isinstance(v, dt.datetime):
        return v.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0").rstrip(".") + "Z"
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, bytes):
        return base64.b64encode(v).decode()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [plain(x) for x in v]
    return v


def run_query(project: str, sql: str, creds, max_bytes: int = MAX_BYTES_BILLED) -> dict:
    """Run `sql` with a bytes cap. Returns {"outcome": "rows", "rows": [...], "columns": [...], job, bytes_billed}
    or {"outcome": "error", "error": "..."}: an access refusal is an answer here, not an exception."""
    from google.api_core import exceptions
    from google.cloud import bigquery

    client = bigquery.Client(project=project, credentials=creds, location=LOCATION)
    cfg = bigquery.QueryJobConfig(maximum_bytes_billed=max_bytes, use_legacy_sql=False, use_query_cache=False)
    try:
        job = client.query(sql, job_config=cfg)
        rows = [{k: plain(v) for k, v in dict(r).items()} for r in job.result()]
    except (exceptions.Forbidden, exceptions.BadRequest, exceptions.NotFound) as ex:
        return {"outcome": "error", "error": f"{type(ex).__name__}: {ex.message if hasattr(ex, 'message') else ex}"}
    return {
        "outcome": "rows",
        "rows": rows,
        "columns": [f.name for f in job.result().schema],
        "job_id": job.job_id,
        "bytes_billed": job.total_bytes_billed,
    }


def select_sql(
    table: str, columns: Sequence[str], order_by: Sequence[str], limit: int, where: str | None = None
) -> str:
    cols = ", ".join(columns)
    return (
        f"SELECT {cols} FROM `{table}`"
        + (f" WHERE {where}" if where else "")
        + f" ORDER BY {', '.join(order_by)} LIMIT {int(limit)}"
    )
