"""Claim 7 — retention is declared, compiled and evidenced.

Every dataset declares a period and a legal basis (contract; a missing one is RETENTION_MISSING in the
contracts gate). Here each table's declaration becomes exactly one mechanism:

  mode: partition   → partition expiration on the table (`time_partitioning.expiration_ms`)
  mode: row         → a daily scheduled DELETE, run as the dataset's custodian (BigQuery has no row
                      expiry); a repeated column (contracts.end_date) compiles to NOT EXISTS over UNNEST
  quarantine table  → a daily DELETE on `_quarantined_at` with the source table's period
  landing bucket    → one lifecycle rule per dataset prefix, age = the dataset's period

**Not claimed: immediate erasure.** Deleted or expired data stays recoverable through BigQuery time
travel (48 h here — the minimum; the default is 7 days) and then fail-safe (7 more days, not
configurable, recoverable only via Cloud Customer Care). The retention report says so in its first line.
"""

from __future__ import annotations

from .contract import Contract
from .findings import Finding
from .schema import harvest_columns

GATE = "retention"
DAY_MS = 86_400_000
TIME_TRAVEL_HOURS = 48
FAIL_SAFE_DAYS = 7
CAVEAT = (
    f"Deletion is not immediate: deleted and expired data stays recoverable through BigQuery time travel "
    f"({TIME_TRAVEL_HOURS} h here, the minimum; 7 days by default) and then fail-safe ({FAIL_SAFE_DAYS} days, "
    f"not configurable, via Cloud Customer Care only) — up to {TIME_TRAVEL_HOURS // 24 + FAIL_SAFE_DAYS} days after the date shown."
)


def delete_sql(c: Contract, table: str, harvest: dict) -> str:
    t = c.tables[table]
    days = c.table_retention_days(table)
    col = t.retention.column
    fq = f"`${{var.project_id}}.{c.dataset}.{table}`"
    info = harvest_columns(harvest)[f"{c.dataset}.{table}"][col]
    if info.repeated_ancestor:
        parent, leaf = col.rsplit(".", 1)
        return (
            f"DELETE FROM {fq} WHERE ARRAY_LENGTH({parent}) > 0 AND NOT EXISTS ("
            f"SELECT 1 FROM UNNEST({parent}) AS x WHERE x.{leaf} IS NULL OR x.{leaf} >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY))"
        )
    if info.type == "TIMESTAMP":
        return f"DELETE FROM {fq} WHERE {col} < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)"
    return f"DELETE FROM {fq} WHERE {col} < DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)"


def quarantine_sql(c: Contract, table: str) -> str:
    days = c.table_retention_days(table)
    return f"DELETE FROM `${{var.project_id}}.{c.dataset}.{table}__quarantine` WHERE _quarantined_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)"


def plan(contracts: list[Contract], harvest: dict) -> list[dict]:
    """One row per table (and quarantine table): what was declared and which mechanism enforces it."""
    rows = []
    for c in sorted(contracts, key=lambda c: c.dataset):
        if c.log_sink:
            rows.append(
                {
                    "dataset": c.dataset,
                    "table": "* (log sink tables)",
                    "period_days": c.retention.period_days,
                    "legal_basis": c.retention.legal_basis,
                    "mode": "partition",
                    "column": "(Logging's partitioning)",
                    "rule": "Cloud Logging writes partitioned tables; the dataset's default partition expiry ages them out (B15)",
                    "mechanism": {
                        "kind": "dataset_default_partition_expiration",
                        "expiration_ms": c.retention.period_days * DAY_MS,
                    },
                }
            )
        for tname, t in sorted(c.tables.items()):
            days = c.table_retention_days(tname)
            row = {
                "dataset": c.dataset,
                "table": tname,
                "period_days": days,
                "legal_basis": c.retention.legal_basis,
                "mode": t.retention.mode,
                "column": t.retention.column,
                "rule": t.retention.rule,
            }
            if t.retention.mode == "partition":
                row["mechanism"] = {"kind": "partition_expiration", "expiration_ms": days * DAY_MS}
            else:
                row["mechanism"] = {
                    "kind": "scheduled_delete",
                    "sql": delete_sql(c, tname, harvest),
                    "schedule": "every 24 hours",
                }
            rows.append(row)
            if any(col.quality for col in t.columns.values()):
                rows.append(
                    {
                        "dataset": c.dataset,
                        "table": f"{tname}__quarantine",
                        "period_days": days,
                        "legal_basis": c.retention.legal_basis,
                        "mode": "row",
                        "column": "_quarantined_at",
                        "rule": "a quarantined row is kept no longer than its source",
                        "mechanism": {
                            "kind": "scheduled_delete",
                            "sql": quarantine_sql(c, tname),
                            "schedule": "every 24 hours",
                        },
                    }
                )
    return rows


def terraform(contracts: list[Contract], harvest: dict) -> tuple[dict, dict]:
    """(estate resources, governance resources) — merged into the compiled layers by compile.py."""
    estate = {
        "google_storage_bucket": {
            "landing": {
                "name": "${var.project_id}-landing",
                "location": "${var.location}",
                "uniform_bucket_level_access": True,
                "public_access_prevention": "enforced",
                "force_destroy": True,
                "labels": {"project": "steward", "managed-by": "steward"},
                "lifecycle_rule": [
                    {
                        "condition": {"age": c.retention.period_days, "matches_prefix": [f"{c.dataset}/"]},
                        "action": {"type": "Delete"},
                    }
                    for c in sorted(contracts, key=lambda c: c.dataset)
                ],
            }
        }
    }
    configs = {}
    for c in sorted(contracts, key=lambda c: c.dataset):
        for row in plan([c], harvest):
            if row["mechanism"]["kind"] != "scheduled_delete":
                continue
            name = f"retention_{c.dataset}_{row['table']}"
            configs[name] = {
                "display_name": f"steward retention {c.dataset}.{row['table']} ({row['period_days']} d)",
                "location": "${var.location}",
                "data_source_id": "scheduled_query",
                "schedule": "every 24 hours",
                "service_account_name": f'${{trimprefix(var.principals["{c.custodian}"], "serviceAccount:")}}',
                "params": {"query": row["mechanism"]["sql"]},
            }
    return estate, {"google_bigquery_data_transfer_config": configs} if configs else {}


def gate(contracts: list[Contract], compiled_estate: dict, compiled_governance: dict, harvest: dict) -> list[Finding]:
    """Compiled == declared, read back from the compiled Terraform (not from plan())."""
    out: list[Finding] = []
    tables = {(n["table_id"]): n for n in compiled_estate["resource"].get("google_bigquery_table", {}).values()}
    datasets = compiled_estate["resource"].get("google_bigquery_dataset", {})
    queries = [
        n["params"]["query"]
        for n in compiled_governance["resource"].get("google_bigquery_data_transfer_config", {}).values()
    ]
    bucket_rules = (
        compiled_estate["resource"].get("google_storage_bucket", {}).get("landing", {}).get("lifecycle_rule", [])
    )
    for c in contracts:
        ds_node = datasets.get(c.dataset, {})
        if str(ds_node.get("max_time_travel_hours")) != str(TIME_TRAVEL_HOURS):
            out.append(
                Finding(
                    "TIME_TRAVEL_NOT_MINIMAL",
                    GATE,
                    c.dataset,
                    f"time travel {ds_node.get('max_time_travel_hours')} h; the caveat promises {TIME_TRAVEL_HOURS} h",
                )
            )
        rule = [r for r in bucket_rules if r["condition"].get("matches_prefix") == [f"{c.dataset}/"]]
        if (
            len(rule) != 1
            or rule[0]["condition"].get("age") != c.retention.period_days
            or rule[0]["action"].get("type") != "Delete"
        ):
            out.append(
                Finding(
                    "RETENTION_NOT_COMPILED",
                    GATE,
                    f"gs://landing/{c.dataset}/",
                    f"landing lifecycle must delete after {c.retention.period_days} days",
                )
            )
        for tname, t in c.tables.items():
            days = c.table_retention_days(tname)
            target = f"{c.dataset}.{tname}"
            node = tables.get(tname)
            if t.retention.mode == "partition":
                got = (node or {}).get("time_partitioning", {}).get("expiration_ms")
                if got != days * DAY_MS:
                    out.append(
                        Finding(
                            "RETENTION_MISMATCH",
                            GATE,
                            target,
                            f"declared {days} d; compiled partition expiration {got} ms (want {days * DAY_MS})",
                        )
                    )
            else:
                hits = [
                    q
                    for q in queries
                    if f".{c.dataset}.{tname}`" in q
                    and f"INTERVAL {days} DAY" in q
                    and t.retention.column.rsplit(".", 1)[-1] in q
                ]
                if len(hits) != 1:
                    out.append(
                        Finding(
                            "RETENTION_NOT_COMPILED",
                            GATE,
                            target,
                            f"row retention of {days} d on {t.retention.column} has {len(hits)} compiled DELETE(s); want exactly 1",
                        )
                    )
            if any(col.quality for col in t.columns.values()):
                q = [x for x in queries if f".{c.dataset}.{tname}__quarantine`" in x and f"INTERVAL {days} DAY" in x]
                if len(q) != 1:
                    out.append(
                        Finding(
                            "RETENTION_NOT_COMPILED",
                            GATE,
                            f"{target}__quarantine",
                            f"quarantine retention of {days} d has {len(q)} compiled DELETE(s)",
                        )
                    )
    return out


def report(contracts: list[Contract], harvest: dict, waivers: list[dict], evidence: dict | None = None) -> dict:
    """The retention report. Line one is the caveat — always."""
    rows = plan(contracts, harvest)
    declared = {f"{r['dataset']}.{r['table']}" for r in rows}
    for table in sorted(harvest):
        if table not in declared and not table.endswith("__quarantine"):
            w = next((w for w in waivers if w.get("target") == table), None)
            rows.append(
                {
                    "dataset": table.split(".")[0],
                    "table": table.split(".")[1],
                    "period_days": None,
                    "legal_basis": None,
                    "mode": None,
                    "mechanism": {"kind": "none — held at `restricted`"},
                    "status": f"NO DECLARATION — waived by {w['id']} until {w['expires']}"
                    if w
                    else "NO DECLARATION — build red",
                }
            )
    for r in rows:
        if "status" in r:
            continue
        ev = (evidence or {}).get(f"{r['dataset']}.{r['table']}")
        r["evidenced"] = ev
        r["status"] = "evidenced" if ev else "compiled (not yet evidenced live — T011/T017)"
    return {"caveat": CAVEAT, "rows": rows}
