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
    """Claim 1's gate: detect personal data by value, then compare with the contracts."""
    from steward import io
    from steward.core.classify import detect
    from steward.core.findings import report
    from steward.core.gate_classification import gate
    from steward.core.validate import load_contract

    scan_date = date.fromisoformat(args.scan_date) if args.scan_date else datetime.now(UTC).date()
    detections = detect(io.synthetic_columns(limit=args.limit), scan_date)
    contracts = [c for c in (load_contract(n, d)[0] for n, d in io.contract_docs().items()) if c]
    findings = gate(detections, contracts)
    flagged = [d for d in detections if d.kinds]
    print(
        f"scanned {len(detections)} columns (row limit {args.limit or 'none'}); personal data found in {len(flagged)}"
    )
    code, lines = report("classification", findings)
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
    s.add_argument("--scan-date", help="ISO date birth dates are judged against (default: today, UTC)")
    args = parser.parse_args(argv)
    if args.cmd == "version":
        from steward import __version__

        print(__version__)
        return 0
    return {"validate": cmd_validate, "scan": cmd_scan}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
