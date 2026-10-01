"""Shared by evals only. The planted manifest is loaded here and nowhere else."""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def load_planted() -> dict:
    return json.loads((REPO / "synthetic" / "_planted.json").read_text())
