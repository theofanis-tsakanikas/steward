#!/usr/bin/env python3
"""terraform fmt -check and validate every layer under infra/, with no backend and no credentials."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def layers() -> list[Path]:
    return sorted(
        p for p in (REPO / "infra").iterdir() if p.is_dir() and (any(p.glob("*.tf")) or any(p.glob("*.tf.json")))
    )


def run(cmd: list[str], cwd: Path) -> int:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        sys.stdout.write(r.stdout + r.stderr)
    return r.returncode


def main() -> int:
    found = layers()
    if not found:
        print("ok tf-validate: no layers yet")
        return 0
    bad: list[str] = []
    if run(["terraform", "fmt", "-check", "-recursive", "infra"], REPO):
        bad.append("fmt")
    for layer in found:
        rel = layer.relative_to(REPO)
        if run(["terraform", "init", "-backend=false", "-input=false", "-no-color"], layer) or run(
            ["terraform", "validate", "-no-color"], layer
        ):
            bad.append(str(rel))
        else:
            print(f"ok {rel}")
    if bad:
        print(f"FAIL tf-validate: {', '.join(bad)}")
        return 1
    print(f"ok tf-validate: {len(found)} layer(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
