"""Shared by evals only. The planted ground truth is loaded here and nowhere else."""

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLANTED = REPO / "evals" / "ground_truth" / "planted.json"


def load_planted() -> dict:
    return json.loads(PLANTED.read_text())
