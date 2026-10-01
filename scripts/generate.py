#!/usr/bin/env python3
"""Regenerate every generated artefact; with --check, regenerate in memory and fail on any diff."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def artefacts() -> dict[Path, str]:
    """path -> expected content. Filled in as generators land."""
    return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    stale: list[str] = []
    for path, content in artefacts().items():
        current = path.read_text() if path.exists() else None
        if current == content:
            continue
        if args.check:
            stale.append(str(path.relative_to(REPO)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            print(f"wrote {path.relative_to(REPO)}")
    if stale:
        for s in stale:
            print(f"GENERATED_STALE {s}")
        print("FAIL generate --check: regenerate with `make generate` and commit")
        return 1
    print(f"ok generate{' --check' if args.check else ''}: {len(artefacts())} artefact(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
