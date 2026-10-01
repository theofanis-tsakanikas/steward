#!/usr/bin/env python3
"""Print the first N rows of every synthetic table — the T001 checkpoint sample."""

import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
for path in sorted(DATA.glob("*.jsonl")):
    print(f"\n── {path.stem} (first {n}) " + "─" * 40)
    for line in path.read_text().splitlines()[:n]:
        print(json.dumps(json.loads(line), ensure_ascii=False))
