"""Sync and reconcile: build the desired catalog from the estate, send only what changed, report.

Doctrine 1, the catalog half: if a sync fails, BigQuery is untouched and the catalog is marked STALE with
the age of the last good sync — fail open on documentation, loudly, with a deadline.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from steward import io, pipeline
from steward.core import catalog as C
from steward.core.classify import detect
from steward.core.findings import Finding
from steward.core.lifecycle import states

PROJECT = "halverra-data"  # the BigQuery project in catalog keys; live, the real project id
STALE_AFTER_HOURS = 24


def model() -> dict:
    return io.load_yaml(io.REPO / "catalog" / "collibra.yaml")


def desired(e: pipeline.Estate, mode: str = "MOCK", group_ids: dict[str, str] | None = None) -> list[dict]:
    """The catalog this estate should have. `group_ids` defaults to the mock's directory; REAL mode passes the
    instance's (catalog/collibra.instance.yaml)."""
    m = model()
    history = json.loads((io.REPO / "evals" / "lineage" / "query_history.json").read_text())
    lk, (_, _, detail) = pipeline.lineage(e, io.REPO / "lookml", history)
    usage = json.loads((io.REPO / "evals" / "marketplace" / "looker_usage.json").read_text())
    contracted = {c.dataset for c in e.contracts}
    legacy_cols = {k: v for k, v in io.synthetic_columns().items() if k.split(".")[0] not in contracted}
    detections = {d.column: d.kinds for d in detect(legacy_cols, pipeline.synthetic_anchor())}
    glossary: dict[str, dict] = {}
    for vname, v in lk["views"].items():
        for fname, f in v["fields"].items():
            for t in f.get("tags", []):
                if t.startswith("glossary:"):
                    term = t.split(":", 1)[1].replace("_", " ").title()
                    g = glossary.setdefault(term, {"definitions": [], "dashboards": []})
                    g["definitions"].append(f"{vname}.{fname}: {f['type']}({f.get('sql')}) where {f.get('filters')}")
                    g["dashboards"] += [
                        d
                        for d, rows in detail["dashboards"].items()
                        if any(r["field"] == f"{vname}.{fname}" for r in rows)
                    ]
    return C.build(
        e.contracts,
        e.harvest,
        PROJECT,
        m["community"],
        detail,
        states(usage),
        glossary,
        detections,
        io.waivers_doc().get("waivers", []),
        group_ids if group_ids is not None else m["user_groups"],
        mode,
    )


def sync(client, e: pipeline.Estate, at: str, last_good: str | None = None) -> dict:
    want = desired(e, client.mode)
    last_good = last_good or (client.last_good_sync() if hasattr(client, "last_good_sync") else None)
    changes = C.diff(want, client.current(), at)
    report = {"mode": client.mode, "run_at": at, "desired_commands": len(want), "changes_sent": len(changes)}
    try:
        result = client.import_job(changes, at) if changes else {"created": 0, "updated": 0}
        report |= {
            "status": "ok",
            "created": result.get("created", 0),
            "updated": result.get("updated", 0),
            "last_good_sync": at,
        }
    except Exception as exc:  # the catalog fails open, loudly
        report |= {"status": "failed", "error": str(exc), "last_good_sync": last_good}
    report["stale"] = stale_marker(report, at)
    if hasattr(client, "record_run"):
        client.record_run(report)
    return report


def stale_marker(report: dict, now: str) -> str | None:
    last = report.get("last_good_sync")
    if report.get("status") == "ok":
        return None
    if not last:
        return "STALE — never synced"
    age = datetime.fromisoformat(now.replace("Z", "+00:00")) - datetime.fromisoformat(last.replace("Z", "+00:00"))
    hours = int(age.total_seconds() // 3600)
    return f"STALE — last good sync {last} ({hours} h ago){'; past the 24 h deadline' if hours >= STALE_AFTER_HOURS else ''}"


def reconcile(client, e: pipeline.Estate, at: str) -> dict:
    harvested = {t.split(".")[0] for t in e.harvest}
    pending = frozenset(c.dataset for c in e.contracts if c.log_sink and c.dataset not in harvested)
    r = C.reconcile(e.harvest, client.current(), desired(e, client.mode), PROJECT, pending)
    return {"mode": client.mode, "reconciled_at": at, **r}


def mock(state: Path | None = None):
    from steward.adapters.collibra.mock import MockCollibra

    return MockCollibra.open(io.REPO / "catalog" / "collibra.yaml", state)


# ── the gate ─────────────────────────────────────────────────────────────────────────────────────────
GATE_T0, GATE_T1 = "2026-10-01T00:00:00Z", "2026-10-01T00:01:00Z"


def gate(e: pipeline.Estate) -> list[Finding]:
    """Claim 4's build gate: the catalog this estate implies is accepted by the validating mock, a second sync
    changes nothing, the reconciliation is empty, and — read back from the catalog, not from the builder —
    every contracted dataset names its owner, steward and custodian, every contracted column carries the
    classification its contract declares, and the catalog says which mode it was generated for."""
    from steward.adapters.collibra.mock import MockCollibra

    g = "catalog"
    client = MockCollibra(model())
    try:
        first = sync(client, e, GATE_T0)
    except ValueError as exc:  # a group with no id: no default owner (doctrine 3)
        return [Finding("OWNER_GROUP_UNKNOWN", g, str(exc).split(":")[0], str(exc))]
    if first["status"] != "ok":
        return [Finding("CATALOG_REJECTED", g, first["error"].split()[0], first["error"])]
    out: list[Finding] = []
    second = sync(client, e, GATE_T1)
    if second["status"] != "ok" or second["changes_sent"]:
        out.append(
            Finding(
                "SYNC_NOT_IDEMPOTENT",
                g,
                "second-sync",
                f"a second sync of an unchanged estate sent {second['changes_sent']} command(s); it must send 0",
            )
        )
    rec = reconcile(client, e, GATE_T1)
    for lst, code in (
        ("in_gcp_not_in_catalog", "RECONCILE_MISSING_IN_CATALOG"),
        ("in_catalog_not_in_gcp", "RECONCILE_MISSING_IN_GCP"),
    ):
        out += [Finding(code, g, item, f"{item} right after a sync") for item in rec[lst]]
    out += [
        Finding("RECONCILE_DIFFERS", g, d["resource"], f"{d['resource']} differs from the contract: {d['differs']}")
        for d in rec["in_both_differing"]
    ]
    cur = client.current()
    for c in e.contracts:
        dom = cur.get(("Domain", model()["community"], C.physical_domain(c.dataset)), {})
        for role in ("Owner", "Steward", "Custodian"):
            if not dom.get("responsibilities", {}).get(role):
                out.append(
                    Finding(
                        "CATALOG_OWNER_MISSING",
                        g,
                        f"{c.dataset}:{role}",
                        f"the catalog names no {role} for {c.dataset}",
                    )
                )
        for fqn, _, _, col in c.iter_columns():
            ds, tbl, path = fqn.split(".", 2)
            asset = cur.get(("Asset", model()["community"], C.physical_domain(ds), f"{PROJECT}.{ds}.{tbl}.{path}"))
            said = asset["attributes"].get("Personal Data Classification", [{}])[0].get("value") if asset else None
            if said != col.classification.value:
                out.append(
                    Finding(
                        "CLASSIFICATION_MISMATCH",
                        g,
                        fqn,
                        f"the contract says {col.classification.value!r}, the catalog says {said!r}",
                    )
                )
    comm = cur.get(("Community", model()["community"]), {})
    if f"catalog mode: {client.mode}" not in comm.get("description", ""):
        out.append(
            Finding("MODE_UNSTATED", g, "community", "the catalog does not say which mode generated it (doctrine 2)")
        )
    return out
