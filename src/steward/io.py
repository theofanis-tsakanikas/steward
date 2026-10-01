"""File I/O for the repository's declarative inputs. Outside core on purpose: core takes dicts."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "contracts"
SYNTHETIC = REPO / "synthetic"


class DuplicateKeyError(ValueError):
    pass


class _StrictLoader(yaml.SafeLoader):
    """safe_load keeps the LAST of two duplicate keys, silently. A contract declaring `ref_2:` twice
    would show a reviewer one classification and load the other — so a duplicate key is an error."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise DuplicateKeyError(f"duplicate key {key!r} at line {key_node.start_mark.line + 1}")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_yaml(path: Path) -> dict:
    return yaml.load(path.read_text(), Loader=_StrictLoader) or {}


def contract_docs(root: Path = CONTRACTS) -> dict[str, dict]:
    stray = sorted(str(p.relative_to(root)) for p in root.rglob("*.y*ml") if p.suffix == ".yml" or p.parent != root)
    if stray:
        raise ValueError(f"contracts must be contracts/*.yaml; found {stray} (they would be silently ignored)")
    return {p.stem: load_yaml(p) for p in sorted(root.glob("*.yaml")) if not p.name.startswith("_")}


def roles_doc(root: Path = CONTRACTS) -> dict:
    return load_yaml(root / "_roles.yaml")


def waivers_doc(root: Path = CONTRACTS) -> dict:
    p = root / "_waivers.yaml"
    return load_yaml(p) if p.exists() else {}


def harvest(root: Path = SYNTHETIC) -> dict:
    """The offline harvest: the generator's schema, which knows nothing about contracts."""
    return json.loads((root / "data" / "_schema.json").read_text())
