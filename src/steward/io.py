"""File I/O for the repository's declarative inputs. Outside core on purpose: core takes dicts."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "contracts"
SYNTHETIC = REPO / "synthetic"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def contract_docs(root: Path = CONTRACTS) -> dict[str, dict]:
    return {p.stem: load_yaml(p) for p in sorted(root.glob("*.yaml")) if not p.name.startswith("_")}


def roles_doc(root: Path = CONTRACTS) -> dict:
    return load_yaml(root / "_roles.yaml")


def waivers_doc(root: Path = CONTRACTS) -> dict:
    p = root / "_waivers.yaml"
    return load_yaml(p) if p.exists() else {}


def harvest(root: Path = SYNTHETIC) -> dict:
    """The offline harvest: the generator's schema, which knows nothing about contracts."""
    return json.loads((root / "data" / "_schema.json").read_text())
