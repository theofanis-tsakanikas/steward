"""The offline pipeline, assembled once: load the declarative inputs, validate, compile.

Outside core (it reads files); every decision it reaches is a core function.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date

from steward import io
from steward.core.compile import compile_controls, compiled_column_tags, render
from steward.core.compile_marketplace import compile_marketplace
from steward.core.compile_seats import compile_seats
from steward.core.contract import Contract, Roles
from steward.core.marketplace import active_grants, decide, load_ledger
from steward.core.validate import load_contract


@dataclass
class Estate:
    contracts: list[Contract]
    broken: frozenset[str]
    roles: Roles
    harvest: dict
    ledger: dict = field(default_factory=dict)
    ledger_findings: list = field(default_factory=list)
    compiled: dict[str, dict] = field(default_factory=dict)

    @property
    def compiled_tags(self) -> dict[str, str | None]:
        return compiled_column_tags(self.compiled["infra/estate/generated.tf.json"])

    def rendered(self) -> dict[str, str]:
        return render(self.compiled)


def load(
    contract_docs: dict | None = None,
    roles_doc: dict | None = None,
    harvest: dict | None = None,
    ledger: dict | None = None,
) -> Estate:
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
    lg = io.load_yaml(io.REPO / "marketplace" / "ledger.yaml") if ledger is None else ledger
    e = Estate(contracts, broken, roles, hv, lg)
    e.compiled = compile_controls(contracts, roles, hv)
    parsed, e.ledger_findings = load_ledger(lg)
    # an invalid ledger grants nothing (doctrine 1); the marketplace gate reports why
    active = active_grants(decide(parsed, contracts, roles), parsed.as_of) if parsed else []
    e.compiled |= compile_marketplace(contracts, active)
    e.compiled |= compile_seats(contracts, roles, active)
    return e


def synthetic_anchor() -> date:
    """The synthetic data's "today" — what an offline scan judges ages against, so CI does not drift
    as the calendar moves. A live scan uses the capture timestamp instead."""
    return date.fromisoformat(json.loads((io.SYNTHETIC / "data" / "_meta.json").read_text())["anchor_date"])


def iam_snapshot(e: Estate, captured_at: str) -> dict:
    """What the estate's dataset IAM would hold if exactly the compiled Terraform were applied — the
    offline stand-in for a live getIamPolicy capture (T016), which has the same shape."""
    import re

    seat = re.compile(r'^\$\{var\.(?:principals|grantees)\["([^"]+)"\]\}$')
    bindings = []
    for layer in ("infra/governance/generated.tf.json", "infra/marketplace/generated.tf.json"):
        for node in e.compiled[layer]["resource"].get("google_bigquery_dataset_iam_member", {}).values():
            m = seat.match(node["member"])
            if not m:
                continue  # e.g. the audit sink's writer identity
            bindings.append(
                {
                    "dataset": node["dataset_id"],
                    "member": m.group(1),
                    "role": node["role"],
                    "condition": node.get("condition"),
                }
            )
    return {
        "captured_at": captured_at,
        "source": "compiled Terraform (offline) — not evidence; a live getIamPolicy capture replaces it in T016",
        "bindings": sorted(bindings, key=lambda b: (b["dataset"], b["member"], b["role"])),
    }


class ConnectionAccess:
    """What the Looker connection's role sees, column by column, from the compiled Terraform."""

    def __init__(self, e: Estate, role: str):
        from steward.core.compile import seats_for
        from steward.core.simulate import effective, model

        self._am = model(e.compiled["infra/estate/generated.tf.json"], e.compiled["infra/governance/generated.tf.json"])
        self._effective = effective
        seats = {s for c in e.contracts for s in seats_for(e.roles, role, c)}
        if len(seats) != 1:
            raise ValueError(f"the connection role {role!r} must be a single seat, got {sorted(seats)}")
        self.seat = seats.pop()
        self.tagged = {c for c, t in self._am.column_tag.items() if t}

    def __call__(self, column: str) -> str:
        return self._effective(self._am, self.seat, column)


def lineage(e: Estate, lookml_root, history: dict):
    """history = {"captured_at": ..., "jobs": [...]} — the job history and when it was taken."""
    from steward.adapters.looker import parse
    from steward.core.lineage import evaluate

    lk = parse(lookml_root)
    catalog = {fqn for c in e.contracts for fqn, _, _, _ in c.iter_columns()}
    tables = {f"{c.dataset}.{t}" for c in e.contracts for t in c.tables}
    kinds = {fqn: list(col.kinds) for c in e.contracts for fqn, _, _, col in c.iter_columns()}
    cache: dict[str, ConnectionAccess] = {}

    def access_for(role: str) -> ConnectionAccess:
        if role not in cache:
            cache[role] = ConnectionAccess(e, role)
        return cache[role]

    return lk, evaluate(lk, history["jobs"], catalog, tables, access_for, kinds, history["captured_at"])
