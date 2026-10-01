"""The offline pipeline, assembled once: load the declarative inputs, validate, compile.

Outside core (it reads files); every decision it reaches is a core function.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from steward import io
from steward.core.compile import compile_controls, compiled_column_tags, render
from steward.core.contract import Contract, Roles
from steward.core.validate import load_contract


@dataclass
class Estate:
    contracts: list[Contract]
    broken: frozenset[str]
    roles: Roles
    harvest: dict
    compiled: dict[str, dict] = field(default_factory=dict)

    @property
    def compiled_tags(self) -> dict[str, str | None]:
        return compiled_column_tags(self.compiled["infra/estate/generated.tf.json"])

    def rendered(self) -> dict[str, str]:
        return render(self.compiled)


def load(contract_docs: dict | None = None, roles_doc: dict | None = None, harvest: dict | None = None) -> Estate:
    docs = io.contract_docs() if contract_docs is None else contract_docs
    contracts, names = [], set()
    for name, doc in sorted(docs.items()):
        c, _ = load_contract(name, doc)
        if c:
            contracts.append(c)
            names.add(c.dataset)
    # A contract that fails to load protects nothing — under its file name AND whatever dataset it
    # claims (a typo in `dataset:` must not make the real dataset look merely uncontracted).
    claimed = {str(d.get("dataset")) for d in docs.values() if isinstance(d, dict) and d.get("dataset")}
    broken = (frozenset(docs) | frozenset(claimed)) - names
    roles = Roles.model_validate(io.roles_doc() if roles_doc is None else roles_doc)
    hv = io.harvest() if harvest is None else harvest
    e = Estate(contracts, broken, roles, hv)
    e.compiled = compile_controls(contracts, roles, hv)
    return e


def synthetic_anchor() -> date:
    """The synthetic data's "today" — what an offline scan judges ages against, so CI does not drift
    as the calendar moves. A live scan uses the capture timestamp instead."""
    return date.fromisoformat(json.loads((io.SYNTHETIC / "data" / "_meta.json").read_text())["anchor_date"])
