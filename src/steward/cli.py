"""steward — the command line."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="steward", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version", help="print the version")
    args = parser.parse_args(argv)
    if args.cmd == "version":
        from steward import __version__

        print(__version__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
