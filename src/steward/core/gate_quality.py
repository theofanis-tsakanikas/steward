"""Claim 5's gate: source = loaded + quarantined, always, and every quarantined row is attributed.

All three numbers come from outside the rules engine: the source count is taken from the source before
the rules run, the loaded and quarantined counts from what was actually written. A loader that drops a
row anywhere between the engine and the destination is caught here, by name.
"""

from __future__ import annotations

from .findings import Finding

GATE = "quality"
REQUIRED = ("run_id", "table", "row_key", "rule_ids", "routed_to")


def gate(counts: dict[str, dict[str, int]], quarantine: dict[str, list[dict]]) -> list[Finding]:
    """counts: {table: {source, loaded, quarantined}} — each counted by a reader of its own.
    quarantine: {table: [records as written]}."""
    out: list[Finding] = []
    for table, c in sorted(counts.items()):
        if c["source"] != c["loaded"] + c["quarantined"]:
            out.append(
                Finding(
                    "QUALITY_ROWS_LOST",
                    GATE,
                    table,
                    f"source {c['source']} ≠ loaded {c['loaded']} + quarantined {c['quarantined']} — {c['source'] - c['loaded'] - c['quarantined']} row(s) unaccounted for",
                    evidence=c,
                )
            )
    for table, recs in sorted(quarantine.items()):
        keys = [r.get("row_key") for r in recs]
        for r in recs:
            missing = [k for k in REQUIRED if not r.get(k)]
            if missing:
                out.append(
                    Finding(
                        "QUARANTINE_UNATTRIBUTED", GATE, table, f"quarantined row {r.get('row_key')!r} lacks {missing}"
                    )
                )
            if "row" not in r:
                out.append(
                    Finding(
                        "QUARANTINE_PAYLOAD_MISSING",
                        GATE,
                        table,
                        f"quarantined row {r.get('row_key')!r} kept no payload — a row that cannot be repaired has been dropped",
                    )
                )
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        if dupes:
            out.append(Finding("QUARANTINE_KEY_COLLISION", GATE, table, f"row keys not unique: {dupes[:3]}"))
    return out
