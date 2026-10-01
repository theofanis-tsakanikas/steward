"""Claim 1's gate: no column in which personal data was found by value goes without a policy tag.

Three inputs, met here for the first time: the detector's output (values only), the contracts, and the
**compiled** estate — the tag each column will actually carry. A column passes only if the contract
classifies it as tagged AND declares every kind found AND the compiled schema carries its tag.

Tables no contract declares are the one bounded exception (docs/DECISIONS.md B7): their PII passes
only if the compiler tagged every such column `restricted` — no reader, no masking, denied to every
role (doctrine 1) — and only while the CONTRACT_MISSING waiver lives; when it expires the contracts
gate goes red. A dataset whose contract fails to load gets no such grace: its PII blocks here too.

Doctrine 7: this gate takes no waivers as input. The only ways past a finding are to tag the column
or to remove the data.
"""

from __future__ import annotations

from .classify import UNSCHEMED, ColumnDetection
from .compile import RESTRICTED
from .contract import LOG_SINK_TABLE, Contract
from .findings import Finding

GATE = "classification"


def gate(
    detections: list[ColumnDetection],
    contracts: list[Contract],
    compiled_tags: dict[str, str | None],
    broken_datasets: frozenset[str] = frozenset(),
) -> list[Finding]:
    declared: dict[str, object] = {}
    tables: set[str] = set()
    sinks = {c.dataset: c.log_sink for c in contracts if c.log_sink}
    contracted = {c.dataset for c in contracts}
    for c in contracts:
        for fqn, _, _, col in c.iter_columns():
            declared[fqn] = col
        tables.update(f"{c.dataset}.{t}" for t in c.tables)

    out: list[Finding] = []
    for d in detections:
        if not d.kinds:
            continue
        kinds = ", ".join(d.kinds)
        ev = {"hits": d.hits, "n_values": d.n_values}
        dataset = d.column.split(".")[0]
        table = ".".join(d.column.split(".")[:2])
        tag = compiled_tags.get(d.column)
        if dataset in broken_datasets:
            out.append(
                Finding(
                    "PII_CONTRACT_BROKEN",
                    GATE,
                    d.column,
                    f"{kinds} found by value; the contract for {dataset} does not load, so nothing protects it",
                    evidence=ev,
                )
            )
        elif dataset in sinks and LOG_SINK_TABLE.match(table.split(".", 1)[1]):
            extra = sorted(set(d.kinds) - set(sinks[dataset].personal_kinds))
            if extra:
                out.append(
                    Finding(
                        "PII_UNDECLARED_COLUMN",
                        GATE,
                        d.column,
                        f"{', '.join(extra)} found in a log-sink dataset that declares only {sinks[dataset].personal_kinds}",
                        evidence=ev,
                    )
                )
            else:
                out.append(
                    Finding(
                        "PII_IN_LOG_SINK",
                        GATE,
                        d.column,
                        f"{kinds} in Cloud Logging's table, as the contract declares; dataset-level readers only",
                        severity="info",
                        evidence=ev,
                    )
                )
        elif UNSCHEMED in d.column:
            out.append(
                Finding(
                    "PII_UNDECLARED_COLUMN",
                    GATE,
                    d.column,
                    f"{kinds} found by value in a field the schema does not declare",
                    evidence=ev,
                )
            )
        elif table not in tables and dataset in contracted:
            out.append(
                Finding(
                    "PII_UNDECLARED_COLUMN",
                    GATE,
                    d.column,
                    f"{kinds} found by value in a table {dataset}'s contract does not declare",
                    evidence=ev,
                )
            )
        elif table not in tables:
            if tag == RESTRICTED:
                out.append(
                    Finding(
                        "PII_HELD_AT_SAFE_STATE",
                        GATE,
                        d.column,
                        f"{kinds} found by value; no contract — compiled `restricted`, denied to every role",
                        severity="info",
                        evidence=ev,
                    )
                )
            else:
                out.append(
                    Finding(
                        "PII_UNTAGGED",
                        GATE,
                        d.column,
                        f"{kinds} found by value; no contract and the compiled schema does not hold it at `restricted`",
                        evidence=ev,
                    )
                )
        elif d.column not in declared:
            out.append(
                Finding(
                    "PII_UNDECLARED_COLUMN",
                    GATE,
                    d.column,
                    f"{kinds} found by value; the contract does not declare this column",
                    evidence=ev,
                )
            )
        else:
            col = declared[d.column]
            if not col.classification.tagged:
                total = sum(d.hits.get(k, 0) for k in d.kinds)
                out.append(
                    Finding(
                        "PII_UNTAGGED",
                        GATE,
                        d.column,
                        f"{kinds} found by value ({total}/{d.n_values} values) but the contract classifies it `{col.classification}` — no policy tag, no masking",
                        evidence=ev,
                    )
                )
                continue
            if not tag:
                out.append(
                    Finding(
                        "PII_UNTAGGED",
                        GATE,
                        d.column,
                        "the contract tags it but the compiled schema carries no policy tag",
                        evidence=ev,
                    )
                )
            missing = sorted(set(d.kinds) - set(col.kinds))
            if missing:
                out.append(
                    Finding(
                        "KIND_UNDECLARED",
                        GATE,
                        d.column,
                        f"found {', '.join(missing)} by value; the contract declares only {', '.join(col.kinds)} — role ceilings are judged on declared kinds, so the stricter reading wins",
                        evidence=ev,
                    )
                )
    return out
