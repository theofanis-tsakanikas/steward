"""steward — the command line. Thin: it loads files, calls the core, prints findings."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime


def _today(s: str | None) -> date:
    # Waivers expire against the real calendar (doctrine 6): CI must go red the day one lapses.
    return date.fromisoformat(s) if s else datetime.now(UTC).date()


def cmd_validate(args: argparse.Namespace) -> int:
    from steward import io
    from steward.core.findings import report
    from steward.core.validate import validate_all

    _, findings = validate_all(io.contract_docs(), io.roles_doc(), io.waivers_doc(), io.harvest(), _today(args.today))
    code, lines = report("contracts", findings)
    print("\n".join(lines))
    return code


def cmd_scan(args: argparse.Namespace) -> int:
    """Claim 1's gate: detect personal data by value, then compare with the contracts and the compiled tags."""
    from steward import io, pipeline
    from steward.core.classify import detect
    from steward.core.findings import report
    from steward.core.gate_classification import gate

    scan_date = date.fromisoformat(args.scan_date) if args.scan_date else pipeline.synthetic_anchor()
    e = pipeline.load()
    detections = detect(io.synthetic_columns(limit=args.limit), scan_date)
    findings = gate(detections, e.contracts, e.compiled_tags, e.broken)
    flagged = [d for d in detections if d.kinds]
    print(
        f"scanned {len(detections)} columns (row limit {args.limit or 'none'}, scan date {scan_date}); personal data found in {len(flagged)}"
    )
    code, lines = report("classification", findings)
    print("\n".join(lines))
    return code


def cmd_compile(args: argparse.Namespace) -> int:
    """The access gate (ceilings, rule/type fit), then the compiled controls."""
    from steward import pipeline
    from steward.core.compile import check
    from steward.core.findings import report

    e = pipeline.load()
    code, lines = report("access", check(e.contracts, e.roles))
    print("\n".join(lines))
    return code


def cmd_quality(args: argparse.Namespace) -> int:
    """Claim 5's gate: run the contract rules over the synthetic sources, then reconcile source with
    what was written (loaded + quarantined)."""
    import tempfile
    from pathlib import Path

    from steward import pipeline, quality_run
    from steward.core.findings import report
    from steward.core.gate_quality import gate

    e = pipeline.load()
    today = date.fromisoformat(args.today) if args.today else pipeline.synthetic_anchor()
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="steward-quality-"))
    summary = quality_run.load_all(e.contracts, out, today)
    counts, quarantine = quality_run.read_destination(out, sorted(summary["tables"]))
    for t, c in counts.items():
        print(f"{t:32} source {c['source']:6}  loaded {c['loaded']:6}  quarantined {c['quarantined']:3}")
    from steward.core.findings import Finding

    findings = gate(counts, quarantine) + [Finding(**f) for t in summary["tables"].values() for f in t["findings"]]
    code, lines = report("quality", findings)
    print("\n".join(lines))
    return code


def cmd_capture(args: argparse.Namespace) -> int:
    """Capture evidence from the live estate (needs the `gcp` extra and credentials; writes evidence/live/)."""
    from pathlib import Path

    from steward.adapters import capture

    return capture.live_main(args.project, args.what or list(capture.ALL), Path(args.out) if args.out else None)


def cmd_marketplace(args: argparse.Namespace) -> int:
    """Claim 6's gate: judge an IAM snapshot against the ledger. Now = the snapshot's capture time."""
    import json
    from pathlib import Path

    from steward import pipeline
    from steward.core.findings import report
    from steward.core.marketplace import decide, gate, load_ledger

    e = pipeline.load()
    ledger, ledger_findings = load_ledger(e.ledger)
    if ledger is None:
        code, lines = report("marketplace", ledger_findings)
        print("\n".join(lines))
        return code
    outcomes = decide(ledger, e.contracts, e.roles)
    snap = json.loads(Path(args.snapshot).read_text()) if args.snapshot else pipeline.iam_snapshot(e, ledger.as_of)
    print(
        f"snapshot: {snap.get('source', args.snapshot)}, captured {snap['captured_at']}, {len(snap['bindings'])} bindings"
    )
    for o in outcomes:
        print(f"  {o.request['id']} {o.status:20} {', '.join(r.code for r in o.reasons) or ''}")
    code, lines = report("marketplace", gate(snap, outcomes, e.contracts, e.roles))
    print("\n".join(lines))
    return code


def cmd_retention(args: argparse.Namespace) -> int:
    """Claim 7's gate: retention declared → compiled (read back from the Terraform) → report."""
    from steward import io, pipeline
    from steward.core import retention
    from steward.core.findings import report as rep

    e = pipeline.load()
    r = retention.report(e.contracts, e.harvest, io.waivers_doc().get("waivers", []))
    print(r["caveat"])
    for row in r["rows"]:
        print(
            f"  {row['dataset']}.{row['table']:28} {row['period_days']!s:>5} d  {row['mechanism']['kind']:22} {row['status']}"
        )
    findings = retention.gate(
        e.contracts,
        e.compiled["infra/estate/generated.tf.json"],
        e.compiled["infra/governance/generated.tf.json"],
        e.harvest,
    )
    code, lines = rep("retention", findings)
    print("\n".join(lines))
    return code


def cmd_lineage(args: argparse.Namespace) -> int:
    """Claim 3's gate: every dashboard field resolves to a catalogued column, sensitive columns reach
    dashboards masked for the connection's role, and LookML lineage agrees with the job history."""
    import json
    from pathlib import Path

    from steward import io, pipeline
    from steward.core.findings import report

    e = pipeline.load()
    jobs_file = Path(args.jobs) if args.jobs else io.REPO / "evals" / "lineage" / "query_history.json"
    history = json.loads(jobs_file.read_text())
    lk, (findings, graph, _detail) = pipeline.lineage(
        e, Path(args.lookml) if args.lookml else io.REPO / "lookml", history
    )
    conns = ", ".join(f"{m}→{v['runs_as_role']}" for m, v in lk["models"].items())
    print(
        f"LookML ({lk['mode']}): {len(lk['views'])} views, {len(lk['explores'])} explores, {len(lk['dashboards'])} dashboards; connections {conns}"
    )
    print(f"job history: {jobs_file.name}, captured {history['captured_at']} (window {30} days)")
    print(f"lineage graph: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    code, lines = report("lineage", findings)
    print("\n".join(lines))
    return code


def cmd_catalog(args: argparse.Namespace) -> int:
    """Claim 4's gate: the generated catalog is accepted by the validating mock, a second sync sends nothing,
    the reconciliation is empty, ownership and classification read back right."""
    from steward import catalog_sync, pipeline
    from steward.core.findings import report

    e = pipeline.load()
    findings = catalog_sync.gate(e)
    print(
        f"catalog (MOCK, in memory): {len(catalog_sync.desired(e))} commands generated from {len(e.contracts)} contracts"
    )
    code, lines = report("catalog", findings)
    print("\n".join(lines))
    return code


def cmd_sync(args: argparse.Namespace) -> int:
    """Claim 4: build the catalog from the estate, send only what changed (twice -> 0), report the mode."""
    import json
    from pathlib import Path

    from steward import catalog_sync, pipeline

    if args.mode == "real":
        print(
            "REAL mode needs a Collibra trial instance (DAY-ONE step 7, T024): the read-back and the instance id map "
            "are not built yet. Nothing was sent. The mock stands, and says so on every surface."
        )
        return 2
    client = catalog_sync.mock(Path(args.state))
    rep = catalog_sync.sync(client, pipeline.load(), args.at)
    client.save()  # also a failed run: the run log is how STALE knows the last good sync
    print(json.dumps(rep, indent=2))
    return 0 if rep["status"] == "ok" else 1


def cmd_reconcile(args: argparse.Namespace) -> int:
    """Claim 4: the reconciliation report — what GCP has that the catalog lacks, and the reverse."""
    import json
    from pathlib import Path

    from steward import catalog_sync, pipeline

    rep = catalog_sync.reconcile(catalog_sync.mock(Path(args.state)), pipeline.load(), args.at)
    print(json.dumps(rep, indent=2))
    return 0 if not (rep["in_gcp_not_in_catalog"] or rep["in_catalog_not_in_gcp"] or rep["in_both_differing"]) else 1


def cmd_evidence(args: argparse.Namespace) -> int:
    """Rebuild the offline fixture evidence the demo reads (or wrap a gate-proof run as evidence)."""
    from pathlib import Path

    from steward import evidence

    if args.gates:
        evidence.record_gates(Path(args.gates))
        print(f"recorded {args.gates} as evidence/{evidence.FIXTURE}/{evidence.GATES_FILE}.json")
        return 0
    names = evidence.write_fixture()
    print(f"evidence/{evidence.FIXTURE}: wrote {len(names)} file(s): {', '.join(names)}")
    return 0


def cmd_evidence_check(args: argparse.Namespace) -> int:
    """Re-verify every evidence file against its digest and the repository, offline."""
    from steward import evidence
    from steward.core.findings import report

    code, lines = report("evidence", evidence.check())
    print("\n".join(lines))
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="steward", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version", help="print the version")
    v = sub.add_parser("validate", help="contracts alone, together, and against the harvested estate")
    v.add_argument("--today", help="ISO date to evaluate waiver expiry against (default: today, UTC)")
    s = sub.add_parser("scan", help="claim 1: value-based PII detection vs contracts (offline: synthetic data)")
    s.add_argument("--limit", type=int, default=None, help="rows per table, like a sampled DLP job")
    s.add_argument("--scan-date", help="ISO date birth dates are judged against (default: the synthetic anchor date)")
    sub.add_parser("compile", help="claim 2: the access gate (role ceilings, masking/type fit) over the contracts")
    q = sub.add_parser("quality", help="claim 5: rules from contracts, quarantine, source = loaded + quarantined")
    q.add_argument("--out", help="destination directory (default: a temp dir)")
    q.add_argument("--today", help="ISO date for freshness (default: the synthetic anchor date)")
    m = sub.add_parser("marketplace", help="claim 6: requests, named approvals, expiring grants vs an IAM snapshot")
    m.add_argument(
        "--snapshot", help="IAM snapshot JSON (live capture); default: the compiled Terraform at the ledger's as_of"
    )
    sub.add_parser("retention", help="claim 7: retention declared, compiled, reported (caveat first)")
    ln = sub.add_parser(
        "lineage", help="claim 3: dashboard fields resolve, sensitive columns masked, lineage cross-checked"
    )
    ln.add_argument("--lookml", help="LookML project root (default: lookml/)")
    ln.add_argument("--jobs", help="job history JSON (default: the labelled fixture)")
    sub.add_parser("catalog", help="claim 4: the generated catalog is valid, idempotent, reconciled, owned")
    sy = sub.add_parser("sync", help="claim 4: generate the catalog from the estate and send only what changed")
    sy.add_argument(
        "--mode", choices=["mock", "real"], default="mock", help="mock (default, validating) or real Collibra"
    )
    sy.add_argument("--state", default="out/collibra-mock.json", help="the mock's state file")
    sy.add_argument("--at", default=None, help="ISO timestamp of the run (default: now, UTC)")
    rc = sub.add_parser("reconcile", help="claim 4: in GCP not in the catalog · in the catalog not in GCP · differing")
    rc.add_argument("--state", default="out/collibra-mock.json", help="the mock's state file")
    rc.add_argument("--at", default=None, help="ISO timestamp of the run (default: now, UTC)")
    ev = sub.add_parser("evidence", help="rebuild the offline fixture evidence the demo reads")
    ev.add_argument("--mode", choices=["fixture"], default="fixture", help="fixture (offline); live is captured, T012+")
    ev.add_argument("--gates", help="record this `gate_proof.py --json` file as evidence/fixture/gates.json instead")
    cp = sub.add_parser(
        "capture", help="capture evidence from the live estate into evidence/live/ (gcp extra, credentials)"
    )
    cp.add_argument("--project", required=True)
    cp.add_argument("--what", nargs="+", help="access iam dlp dataplex audit history (default: all)")
    cp.add_argument("--out", help="directory to write into (default: evidence/live)")
    sub.add_parser(
        "evidence-check", help="every evidence file matches its digest and the repository; gate-proof recorded"
    )
    args = parser.parse_args(argv)
    if getattr(args, "at", "x") is None:
        from datetime import UTC, datetime

        args.at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.cmd == "version":
        from steward import __version__

        print(__version__)
        return 0
    return {
        "validate": cmd_validate,
        "scan": cmd_scan,
        "compile": cmd_compile,
        "quality": cmd_quality,
        "marketplace": cmd_marketplace,
        "retention": cmd_retention,
        "lineage": cmd_lineage,
        "catalog": cmd_catalog,
        "sync": cmd_sync,
        "reconcile": cmd_reconcile,
        "evidence": cmd_evidence,
        "capture": cmd_capture,
        "evidence-check": cmd_evidence_check,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
