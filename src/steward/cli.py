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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="steward", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version", help="print the version")
    v = sub.add_parser("validate", help="contracts alone, together, and against the harvested estate")
    v.add_argument("--today", help="ISO date to evaluate waiver expiry against (default: today, UTC)")
    args = parser.parse_args(argv)
    if args.cmd == "version":
        from steward import __version__

        print(__version__)
        return 0
    return {"validate": cmd_validate}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
