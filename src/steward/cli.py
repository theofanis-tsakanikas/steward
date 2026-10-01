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
    args = parser.parse_args(argv)
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
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
