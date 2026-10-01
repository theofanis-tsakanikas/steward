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
    # Every column no contract declares — in an uncontracted dataset or a contracted one — is scanned by value and
    # shown with what was found; one the scan did not cover says so instead of "nothing found".
    declared = {fqn for c in e.contracts for fqn, _, _, _ in c.iter_columns()}
    undeclared = {k: v for k, v in io.synthetic_columns().items() if k not in declared}
    detections = {d.column: d.kinds for d in detect(undeclared, pipeline.synthetic_anchor())}
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
        scanned=frozenset(undeclared),
        group_ids=group_ids if group_ids is not None else m["user_groups"],
        mode=mode,
    )


def sync(client, e: pipeline.Estate, at: str, last_good: str | None = None) -> dict:
    """One run. Everything that can fail — the build, the read, the import — is inside the guard: a failed run is
    a report (status failed, error, STALE marker) and a line in the run log, never a traceback with no record.
    On failure the marker is also written into the catalog itself, best effort (doctrine 1: the catalog shows
    a stale marker with its age); the next good sync writes the plain text back."""
    last_good = last_good or (client.last_good_sync() if hasattr(client, "last_good_sync") else None)
    report: dict = {"mode": client.mode, "run_at": at, "desired_commands": None, "changes_sent": None}
    try:
        want = desired(e, client.mode)
        changes = C.diff(want, client.current(), at)
        report |= {"desired_commands": len(want), "changes_sent": len(changes)}
        result = client.import_job(changes, at) if changes else {"created": 0, "updated": 0}
        # REAL returns no counts until its read-back exists (T024): None says "unknown", not "0"
        report |= {
            "status": "ok",
            "created": result.get("created"),
            "updated": result.get("updated"),
            "last_good_sync": at,
        }
    except Exception as exc:  # the catalog fails open, loudly
        error = f"OWNER_GROUP_UNKNOWN: {exc}" if isinstance(exc, C.UnknownOwnerGroup) else str(exc)
        report |= {"status": "failed", "error": error, "last_good_sync": last_good}
    report["stale"] = stale_marker(report, at)
    if report["stale"]:
        report["marker_written"] = _write_marker(client, report["stale"], at)
    if hasattr(client, "record_run"):
        client.record_run(report)
    return report


def _write_marker(client, marker: str, at: str) -> bool:
    try:
        client.import_job(
            [
                {
                    "resourceType": "Community",
                    "identifier": {"name": model()["community"]},
                    "description": C.generated_text(client.mode, marker),
                }
            ],
            at,
        )
        return True
    except Exception:  # the instance may be exactly what is down
        return False


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
    # a log-sink dataset is "pending" only until the model's date (doctrine 6); `at` is the run's own clock
    until = str(model().get("pending_first_write_until", ""))
    live = at[:10] <= until
    pending = frozenset(c.dataset for c in e.contracts if live and c.log_sink and c.dataset not in harvested)
    r = C.reconcile(e.harvest, client.current(), desired(e, client.mode), PROJECT, pending)
    return {"mode": client.mode, "reconciled_at": at, **r}


def mock(state: Path | None = None):
    from steward.adapters.collibra.mock import MockCollibra

    return MockCollibra.open(io.REPO / "catalog" / "collibra.yaml", state)


# ── the gate ─────────────────────────────────────────────────────────────────────────────────────────
GATE_T0, GATE_T1 = "2026-10-01T00:00:00Z", "2026-10-01T00:01:00Z"


def _said(asset: dict | None, name: str) -> str | None:
    return asset["attributes"].get(name, [{}])[0].get("value") if asset else None


def gate(e: pipeline.Estate) -> list[Finding]:
    """Claim 4's build gate: the catalog this estate implies is accepted by the validating mock, a second sync
    changes nothing, the reconciliation is empty, and — READ BACK from the catalog and compared with the
    contracts, not with the builder's own output — every contracted dataset names its owner, steward and
    custodian; every contracted column carries its contract's classification and masking; every dataset its
    retention period and lawful basis; every column no contract declares is held at `restricted`; no glossary
    term arrives already Accepted; and the catalog says which mode generated it."""
    from steward.adapters.collibra.mock import MockCollibra

    g = "catalog"
    client = MockCollibra(model())
    first = sync(client, e, GATE_T0)
    if first["status"] != "ok":
        err = first["error"]
        if err.startswith("OWNER_GROUP_UNKNOWN"):  # a group with no id: no default owner (doctrine 3)
            return [Finding("OWNER_GROUP_UNKNOWN", g, err.split(":")[1].strip(), err)]
        return [Finding("CATALOG_REJECTED", g, err.split()[0], err)]
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
        ("in_catalog_not_generated", "RECONCILE_STALE_GENERATED"),
        ("generated_not_in_catalog", "RECONCILE_GENERATED_MISSING"),
    ):
        out += [Finding(code, g, item, f"{item} right after a sync") for item in rec[lst]]
    out += [
        Finding("RECONCILE_DIFFERS", g, d["resource"], f"{d['resource']} differs from the contract: {d['differs']}")
        for d in rec["in_both_differing"]
    ]

    comm = model()["community"]
    cur = client.current()
    declared: set[str] = set()
    for c in e.contracts:
        dom = cur.get(("Domain", comm, C.physical_domain(c.dataset)), {})
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
        schema = cur.get(("Asset", comm, C.physical_domain(c.dataset), f"{PROJECT}.{c.dataset}"))
        for attr, want, code in (
            ("Retention Period", f"{c.retention.period_days} days", "CATALOG_RETENTION_MISMATCH"),
            ("Lawful Basis", c.lawful_basis, "CATALOG_LAWFUL_BASIS_MISMATCH"),
        ):
            if _said(schema, attr) != want:
                out.append(
                    Finding(code, g, c.dataset, f"the contract says {want!r}, the catalog says {_said(schema, attr)!r}")
                )
        for fqn, _, _, col in c.iter_columns():
            declared.add(f"{PROJECT}.{fqn}")
            asset = cur.get(("Asset", comm, C.physical_domain(c.dataset), f"{PROJECT}.{fqn}"))
            said = _said(asset, "Personal Data Classification")
            if said != col.classification.value:
                out.append(
                    Finding(
                        "CLASSIFICATION_MISMATCH",
                        g,
                        fqn,
                        f"the contract says {col.classification.value!r}, the catalog says {said!r}",
                    )
                )
            masking = _said(asset, "Masking")
            want_mask = {r: m.value for r, m in col.masking.items()}
            try:
                same = (json.loads(masking) if want_mask else masking) == (want_mask or "none (untagged)")
            except (TypeError, ValueError):
                same = False
            if not same:
                out.append(
                    Finding(
                        "CATALOG_MASKING_MISMATCH",
                        g,
                        fqn,
                        f"the contract says {want_mask or 'untagged'}, the catalog says {masking!r}",
                    )
                )
    # a column the estate has and no contract declares is held at `restricted` — read from the catalog (doctrine 1)
    for k, v in cur.items():
        if k[0] == "Asset" and v["type"]["name"] == "Column" and k[3] not in declared:
            said = _said(v, "Personal Data Classification") or ""
            if not said.startswith("restricted"):
                out.append(
                    Finding(
                        "CATALOG_UNDECLARED_NOT_RESTRICTED",
                        g,
                        k[3],
                        f"no contract declares it; the catalog says {said!r}, not restricted",
                    )
                )
        if k[0] == "Asset" and v["type"]["name"] == "Business Term" and v["status"]["name"] == "Accepted":
            out.append(
                Finding(
                    "CATALOG_SELF_ACCEPTED",
                    g,
                    k[3],
                    "a term drafted from LookML arrived Accepted: only a steward accepts (doctrine 5)",
                )
            )
    if f"catalog mode: {client.mode}" not in cur.get(("Community", comm), {}).get("description", ""):
        out.append(
            Finding("MODE_UNSTATED", g, "community", "the catalog does not say which mode generated it (doctrine 2)")
        )
    return out
