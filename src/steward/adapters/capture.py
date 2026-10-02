"""Captures from the live estate, written as evidence (`evidence/live/*.json`). Every capture says what it asked,
as whom, and what came back; nothing here decides whether the answer is right: `steward.live` and the core do,
offline, on the committed file.

No capture writes to the estate. The one thing a capture creates is BigQuery query jobs (capped, labelled by the
caller's identity) and, for Dataplex, on-demand scan jobs of scans the assurance layer already declared.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from steward import evidence, io
from steward.live import PROBE_PERSON, QUERIES, resolve

SEATS = io.REPO / "infra" / "seats.json"


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def account(name: str, project: str) -> str:
    doc = json.loads(SEATS.read_text())
    aid = {**doc["seats"], **doc["people"]}[name]
    return f"{aid}@{project}.iam.gserviceaccount.com"


def redactor(project: str, number: str | None = None) -> Callable[[str], str]:
    """Evidence is committed to a repository that will be public: the project id, its number and every service
    account address are replaced by a stable placeholder before anything is written."""

    def r(text):
        if not isinstance(text, str):
            return text
        text = re.sub(r"[a-z0-9-]+@" + re.escape(project) + r"\.iam\.gserviceaccount\.com", "<service-account>", text)
        text = text.replace(project, "<project>")
        if number:
            text = text.replace(number, "<project-number>")
        return text

    return r


def capture_access(project: str, run: Callable[[str, str], dict], e=None, redact=lambda s: s) -> dict:
    """One query as each seat. `run(service_account_email, sql)` -> run_query's dict."""
    from steward import pipeline

    e = e or pipeline.load()
    transcripts = []
    plan = [(q, resolve(e, q, s), None) for q in QUERIES for s in q.seats]
    plan.append(
        (QUERIES[0], PROBE_PERSON, "marketplace grantee (B46): the grant opens the dataset, controls are per seat")
    )
    for q, seat, note in plan:
        res = run(account(seat, project), q.sql())
        tr = {
            "query": q.id,
            "seat": seat,
            "table": q.table,
            "sql": q.sql(),
            "outcome": res["outcome"],
            "rows": res.get("rows", []),
        }
        if res["outcome"] == "error":
            tr["error"] = redact(res["error"])
        else:
            tr["job_id"] = res["job_id"]
            tr["bytes_billed"] = res["bytes_billed"]
        if note:
            tr["note"] = note
        transcripts.append(tr)
    return {"captured_at": now(), "limit": 5, "transcripts": transcripts}


def write(name: str, data: dict, claim: str, origin: str, captured_at: str, out: Path | None = None) -> Path:
    """Wrap `data` as a live evidence document and refresh the manifest."""
    root = out or evidence.ROOT / "live"
    doc = evidence.wrap(name, data, "live", claim, origin, {"as_of": captured_at, "captured_at": captured_at})
    path = root / f"{name}.json"
    evidence._write(path, doc)
    if out is None:  # the repository's own evidence/live: the manifest lists it
        evidence.write_manifest()
    return path


# ── claim 1: DLP over a bounded sample of every readable column ──────────────────────────────────────────────────

DLP_REGION = "europe-west1"  # infra/assurance: the template's parent
DLP_TEMPLATE = "steward-inspect"


def capture_dlp(
    project: str,
    *,
    table_meta: Callable[[str], dict],
    read_rows: Callable[[str | None, str], list[dict]],
    inspect: Callable[[dict], dict],
    e=None,
    redact=lambda s: s,
) -> dict:
    """For each synthetic table: plan the sample from the table's live size, read the untagged columns as the identity
    that may (the custodian seat, or the deployer where no contract covers the dataset), have DLP inspect them.

    `table_meta("dataset.table")` -> {"numRows", "numBytes"}; `read_rows(service_account | None, sql)` -> rows;
    `inspect(item)` -> the `content.inspect` response."""
    from steward import pipeline
    from steward.adapters import dlp
    from steward.core.compile_assurance import partition_filter
    from steward.core.sampling import plan_sample

    e = e or pipeline.load()
    tags = e.compiled_tags
    estate = e.compiled["infra/estate/generated.tf.json"]
    custodians = {c.dataset: c.custodian for c in e.contracts}
    tables, all_findings = [], []
    for table, spec in sorted(e.harvest.items()):
        dataset, name = table.split(".", 1)
        leaves = dlp.leaf_columns(spec["fields"])
        scanned, skipped = [], []
        for path, _type, repeated in leaves:
            if repeated:
                skipped.append({"column": path, "reason": "repeated field (not flattened by the capture)"})
            elif tags.get(f"{table}.{path}") is not None:
                skipped.append(
                    {"column": path, "reason": "policy-tagged: already declared sensitive; no reader holds it"}
                )
            else:
                scanned.append(path)
        meta = table_meta(table)
        sample = plan_sample(table, int(meta["numRows"]), int(meta["numBytes"]))
        where = partition_filter(estate, dataset, name, {p: t for p, t, _ in leaves})
        sql = (
            f"SELECT {dlp.select_list(scanned)} FROM `{dataset}.{name}`"
            + (f" WHERE {where}" if where else "")
            + f" LIMIT {sample.rows_limit}"
        )
        seat = custodians.get(dataset)
        who = account(seat, project) if seat else None
        # every column policy-tagged: nothing a reader may inspect, and `SELECT` with an empty list is a syntax error
        rows = read_rows(who, sql) if scanned else []
        found, truncated, requests = [], False, 0
        for offset, part in _offsets(dlp.chunks(rows)):
            f, t, n = dlp.inspect_rows(inspect, scanned, part, offset)
            found += f
            truncated, requests = truncated or t, requests + n
        all_findings += dlp.summarize(table, found)
        tables.append(
            {
                "table": table,
                "read_as": (
                    ("custodian seat" if seat else "deployer (no contract covers this dataset)")
                    if scanned
                    else "not read: every column is policy-tagged, so no reader may inspect it"
                ),
                "sample": sample.as_record(),
                "rows_read": len(rows),
                "columns_scanned": scanned,
                "columns_not_scanned": skipped,
                "requests": requests,
                "truncated": truncated,
            }
        )
    return {
        "captured_at": now(),
        "method": "content.inspect over a bounded SELECT (core/sampling.py), untagged columns only, include_quote=false",
        "template": DLP_TEMPLATE,
        "region": DLP_REGION,
        "tables": tables,
        "findings": all_findings,
        "control": _dlp_control(e, inspect),
    }


CONTROL_ROWS = 200


def _dlp_control(e, inspect) -> dict:
    """The same template over the generator's own rows, every column, read from the repository and not from BigQuery.

    The untagged columns above should come back empty (the contract declares everything sensitive), and an empty
    answer proves nothing unless the same template is shown to find the personal data when it IS there. The values
    are synthetic. Which column holds what is NOT recorded here: `evals/dlp` compares with the planted manifest."""
    from steward.adapters import dlp

    columns = io.synthetic_columns(limit=CONTROL_ROWS)
    per_table: dict[str, dict[str, list]] = {}
    for table in io.harvest():
        prefix = table + "."
        per_table[table] = {k[len(prefix) :]: v for k, v in columns.items() if k.startswith(prefix)}
    tables, found_all = [], []
    for table, cols in sorted(per_table.items()):
        names = sorted(cols)
        cols = {c: v[:CONTROL_ROWS] for c, v in cols.items()}  # a repeated field flattens to more values than rows
        n = max(len(v) for v in cols.values())
        rows = [{c: (cols[c][i] if i < len(cols[c]) else None) for c in names} for i in range(n)]
        found, truncated, requests = [], False, 0
        for offset, part in _offsets(dlp.chunks(rows)):
            f, t, r = dlp.inspect_rows(inspect, names, part, offset)
            found += f
            truncated, requests = truncated or t, requests + r
        found_all += dlp.summarize(table, found)
        tables.append({"table": table, "rows": n, "columns": names, "requests": requests, "truncated": truncated})
    return {"rows_per_table": CONTROL_ROWS, "tables": tables, "findings": found_all}


def _offsets(parts: list[list[dict]]):
    off = 0
    for p in parts:
        yield off, p
        off += len(p)


# ── claims 2, 6: who holds what on each dataset, as getIamPolicy says ─────────────────────────────────────────────


def principal_names(project: str) -> dict[str, str]:
    """service account address -> the seat or requester name the contracts use."""
    doc = json.loads(SEATS.read_text())
    return {f"{aid}@{project}.iam.gserviceaccount.com": who for who, aid in {**doc["seats"], **doc["people"]}.items()}


def capture_iam(project: str, datasets: list[str], get_policy: Callable[[str], dict]) -> dict:
    """A snapshot in the shape `pipeline.iam_snapshot` produces and `steward marketplace --snapshot` reads.

    `get_policy(dataset)` -> the dataset's bindings (`access_to_bindings` of its access list; conditions are present).
    A member that is not one of the demo's seats or requesters is not hidden: it is listed under `other_members`."""
    names = principal_names(project)
    bindings, other = [], []
    for ds in sorted(datasets):
        for b in get_policy(ds).get("bindings", []):
            cond = b.get("condition")
            for m in b.get("members", []):
                who = names.get(m.split(":", 1)[1]) if m.startswith("serviceAccount:") else None
                if who is None:
                    other.append(
                        {"dataset": ds, "member": _generic(m, project), "role": b["role"], "condition": bool(cond)}
                    )
                    continue
                bindings.append(
                    {
                        "dataset": ds,
                        "member": who,
                        "role": b["role"],
                        "condition": {k: cond[k] for k in ("title", "description", "expression") if k in cond}
                        if cond
                        else None,
                    }
                )
    key = lambda b: (b["dataset"], b["member"], b["role"])  # noqa: E731
    return {
        "captured_at": now(),
        "source": "live: datasets.get, the access list read as IAM bindings (conditions included)",
        "bindings": sorted(bindings, key=key),
        "other_members": sorted(other, key=lambda b: (b["dataset"], b["member"], b["role"])),
    }


LEGACY_ROLES = {
    "READER": "roles/bigquery.dataViewer",
    "WRITER": "roles/bigquery.dataEditor",
    "OWNER": "roles/bigquery.dataOwner",
}


def access_to_bindings(access: list[dict]) -> list[dict]:
    """A dataset's `access` list as IAM bindings: `[{role, members: [...], condition?}]`.

    An entry without a role is an authorised view, routine or dataset: it grants no principal anything and is left out.
    The legacy role names are the ones BigQuery itself keeps for READER, WRITER and OWNER."""
    out = []
    for a in access:
        role = a.get("role")
        if not role:
            continue
        if "iamMember" in a:
            member = a["iamMember"]
        elif "userByEmail" in a:
            email = a["userByEmail"]
            member = ("serviceAccount:" if email.endswith(".gserviceaccount.com") else "user:") + email
        elif "groupByEmail" in a:
            member = "group:" + a["groupByEmail"]
        elif "specialGroup" in a:
            member = "specialGroup:" + a["specialGroup"]
        elif "domain" in a:
            member = "domain:" + a["domain"]
        else:
            continue
        # a role bound with an IAM Condition is stored under `<role>_withcond_<hash>`; the condition travels beside it
        role = re.sub(r"_withcond_[0-9a-f]+$", "", role)
        b = {"role": LEGACY_ROLES.get(role, role), "members": [member]}
        if a.get("condition"):
            b["condition"] = a["condition"]
        out.append(b)
    return out


def _generic(member: str, project: str) -> str:
    return re.sub(r"[a-z0-9-]+@" + re.escape(project) + r"\.iam\.gserviceaccount\.com", "<service-account>", member)


# ── claim 3, 6: the audit sink and the job history ────────────────────────────────────────────────────────────────

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


def capture_audit(project: str, run: Callable[[str, str], dict], redact: Callable[[str], str]) -> dict:
    """The access review: who ran queries in the last days, read from the audit sink as the audit dataset's steward."""
    res = run(account("group:data-governance@halverra.example", project), ACCESS_REVIEW_SQL)
    names = principal_names(project)
    rows = [{**r, "principal": names.get(r["principal"], redact(r["principal"]))} for r in res.get("rows", [])]
    out = {"captured_at": now(), "sql": ACCESS_REVIEW_SQL, "outcome": res["outcome"], "rows": rows}
    if res["outcome"] == "error":
        out["error"] = redact(res["error"])
    return out


HISTORY_DAYS = 7


def history_sql(datasets: list[str]) -> str:
    """The estate's own job history: what wrote which table, who ran it, what it read. Anonymous result tables
    (`_...` datasets) and other projects' datasets never match the list."""
    names = ", ".join(f"'{d}'" for d in sorted(datasets))
    return f"""
SELECT
  job_id,
  job_type,
  statement_type,
  creation_time,
  user_email AS principal,
  CONCAT(destination_table.dataset_id, '.', destination_table.table_id) AS destination,
  ARRAY(SELECT CONCAT(r.dataset_id, '.', r.table_id) FROM UNNEST(referenced_tables) AS r ORDER BY 1) AS referenced_tables
FROM `region-eu`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {HISTORY_DAYS} DAY)
  AND job_type IN ('LOAD', 'QUERY')
  AND destination_table.dataset_id IN ({names})
ORDER BY creation_time, job_id
""".strip()


def capture_history(
    project: str, run: Callable[[str | None, str], dict], redact: Callable[[str], str], datasets: list[str]
) -> dict:
    """Claim 3, live: the BigQuery job history that wrote the estate's tables, read as the deployer."""
    sql = history_sql(datasets)
    res = run(None, sql)
    names = principal_names(project)
    out = {"captured_at": now(), "window_days": HISTORY_DAYS, "sql": sql, "outcome": res["outcome"], "jobs": []}
    if res["outcome"] == "error":
        out["error"] = redact(res["error"])
        return out
    for r in res["rows"]:
        out["jobs"].append(
            {
                "job_type": r["job_type"],
                "statement_type": r["statement_type"],
                "created": r["creation_time"],
                "principal": names.get(r["principal"], redact(r["principal"])),
                "destination": r["destination"],
                "referenced_tables": r["referenced_tables"],
            }
        )
    return out


# ── the real wiring: credentials, the two REST services, the output files ─────────────────────────────────────────

ALL = ("access", "iam", "dlp", "dataplex", "audit", "history")


def _ok(r) -> None:
    """Like `raise_for_status`, but the error carries what the service said (a bare 400 says nothing)."""
    if not r.ok:
        raise RuntimeError(f"{r.request.method} {r.url.split('?')[0]} -> {r.status_code}: {r.text[:600]}")


def live_main(project: str, what: list[str], out: Path | None = None) -> int:
    """Run the named captures against the live estate and write each as `evidence/live/<name>.json`.

    Credentials are Application Default Credentials: in CI the deployer service account (Workload Identity
    Federation), which may impersonate the seats; on a laptop, whoever `gcloud auth application-default login`
    names, who then needs serviceAccountTokenCreator on the seats."""
    from steward import pipeline
    from steward.adapters import dataplex, gcp

    e = pipeline.load()
    base = gcp.credentials()
    sess = gcp.session(base)
    number = str(sess.get(f"https://cloudresourcemanager.googleapis.com/v1/projects/{project}").json()["projectNumber"])
    known = principal_names(project)
    generic = redactor(project, number)

    def redact(text):
        if not isinstance(text, str):
            return text
        for email, who in known.items():
            text = text.replace(email, who)
        return generic(text)

    def run_as(email, sql):
        return gcp.run_query(project, sql, gcp.credentials(impersonate=email) if email else base)

    def read_rows(email, sql):
        res = run_as(email, sql)
        if res["outcome"] == "error":
            raise RuntimeError(f"read failed as {email or 'the deployer'}: {redact(res['error'])}")
        return res["rows"]

    def table_meta(table):
        ds, name = table.split(".", 1)
        r = sess.get(f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{ds}/tables/{name}")
        _ok(r)
        return r.json()

    def inspect(item):
        parent = f"projects/{project}/locations/{DLP_REGION}"
        body = {"item": item, "inspectTemplateName": f"{parent}/inspectTemplates/{DLP_TEMPLATE}"}
        r = sess.post(f"https://dlp.googleapis.com/v2/{parent}/content:inspect", json=body)
        _ok(r)
        return r.json()

    def get_policy(dataset):
        # datasets.getIamPolicy is not open to this project ("This feature requires allowlisting", first capture):
        # the dataset's own access list is what the Terraform provider writes, conditions included
        url = f"https://bigquery.googleapis.com/bigquery/v2/projects/{project}/datasets/{dataset}"
        r = sess.get(url)
        _ok(r)
        return {"bindings": access_to_bindings(r.json().get("access", []))}

    def rest(method, url, body):
        r = sess.request(method, url, json=body)
        _ok(r)
        return r.json()

    def _one(name):
        if name == "access":
            data = capture_access(project, run_as, e, redact)
            claim, origin = "2", "steward capture: one query per seat, impersonating each seat's service account"
        elif name == "iam":
            datasets = sorted({t.split(".")[0] for t in e.harvest} | {c.dataset for c in e.contracts})
            data = capture_iam(project, datasets, get_policy)
            claim, origin = (
                "2,6",
                "steward capture: datasets.get, the access list (conditions included) read as IAM bindings",
            )
        elif name == "dlp":
            data = capture_dlp(project, table_meta=table_meta, read_rows=read_rows, inspect=inspect, e=e, redact=redact)
            claim, origin = "1", "steward capture: content.inspect over a bounded SELECT"
        elif name == "dataplex":
            scans = e.compiled["infra/assurance/generated.tf.json"]["resource"]["google_dataplex_datascan"]
            ids = sorted(v["data_scan_id"] for v in scans.values())
            data = {
                "captured_at": now(),
                "location": DLP_REGION,
                "scans": [
                    {**s, "message": redact(s["message"])} for s in dataplex.run_scans(rest, project, DLP_REGION, ids)
                ],
            }
            claim, origin = "5", "steward capture: dataScans:run, then the job's data-quality result"
        elif name == "audit":
            data = capture_audit(project, run_as, redact)
            claim, origin = "6", "steward capture: the access-review query over the audit sink"
        elif name == "history":
            data = capture_history(project, run_as, redact, sorted({t.split(".")[0] for t in e.harvest}))
            claim, origin = "3", "steward capture: INFORMATION_SCHEMA.JOBS_BY_PROJECT, read as the deployer"
        else:
            raise SystemExit(f"unknown capture {name!r}; choose from {', '.join(ALL)}")
        return data, claim, origin

    failed = []
    for name in what:
        try:
            data, claim, origin = _one(name)
            path = write(name, data, claim, origin, data["captured_at"], out)
            print(f"captured {name}: {path}")
        except SystemExit:
            raise
        except Exception as ex:  # one capture failing must not cost the others: every error is printed, the exit is 1
            failed.append(name)
            print(f"FAILED {name}: {type(ex).__name__}: {redact(str(ex))}")
    if failed:
        print(f"FAIL capture: {', '.join(failed)}")
        return 1
    return 0
