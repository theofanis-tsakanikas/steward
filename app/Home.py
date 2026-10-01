"""Steward — landing page: what this is, and the one-line state of each claim, from evidence."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import streamlit as st

import _lib

_lib.page(
    "Steward",
    "all seven",
    "A governance layer for a telco's BigQuery estate. **A column that holds personal data without a policy "
    "tag, an owner and a retention period is a build failure**, and the catalog is generated from the estate, "
    "never hand-maintained. Every figure in this app is read from an evidence file whose digest is re-checked "
    "when it is opened.",
)

estate = _lib.data("estate")
cls = _lib.data("classification")
acc = _lib.data("access")
lin = _lib.data("lineage")
qual = _lib.data("quality")
cat = _lib.data("catalog")["scenarios"]
mkt = _lib.data("marketplace")
ret = _lib.data("retention")

columns = [c for d in estate["datasets"] for c in d["columns"]]
tagged = [c for c in columns if c["masking"]]
quarantined = sum(v["quarantined"] for v in qual["counts"].values())
refused = sum(1 for o in mkt["outcomes"] if o["status"] != "granted")

a, b, c, d = st.columns(4)
a.metric("Contracted datasets", len(estate["datasets"]))
b.metric("Declared columns", len(columns), f"{len(tagged)} carry a policy tag")
c.metric("Columns scanned by value", cls["n_columns"], f"{cls['n_values']:,} values")
d.metric("Catalog assets", sum(cat["A_clean"]["assets_by_type"].values()))

rows = [
    (
        "1",
        "No sensitive column is unclassified",
        f"value detector found {cls['value_detector']['tp']} of {cls['n_truth_pairs']} planted (column, kind) pairs; "
        f"names alone found {cls['name_heuristics']['tp']}",
        "Privacy",
    ),
    (
        "2",
        "Same query, different answer, by role",
        f"{acc['checked_column_decisions']:,} seat × column decisions checked against the contracts, "
        f"{len(acc['mismatches'])} mismatches",
        "Privacy",
    ),
    (
        "3",
        "Lineage reaches the dashboard",
        f"{lin['counts']['nodes']} nodes, {lin['counts']['edges']} edges, {lin['counts']['dashboards']} dashboards; "
        f"{len(lin['drift_got'])} planted defects caught",
        "Lineage",
    ),
    (
        "4",
        "The catalog is generated, idempotent, reconciled",
        f"first sync sent {cat['A_clean']['first']['changes_sent']}, second sent "
        f"{cat['A_clean']['second']['changes_sent']}; mode {cat['A_clean']['first']['mode']}",
        "Catalog",
    ),
    (
        "5",
        "A failing row is quarantined, never dropped",
        f"{quarantined} rows quarantined across {len(qual['counts'])} tables; "
        f"{len(qual['missed'])} planted failures missed",
        "Quality",
    ),
    (
        "6",
        "Access is requested, approved by a named human, and expires",
        f"{len(mkt['outcomes'])} requests: {len(mkt['outcomes']) - refused} granted, {refused} not",
        "Marketplace",
    ),
    (
        "7",
        "Retention is declared, enforced and evidenced",
        f"{len(ret['report']['rows'])} tables reported; {len(ret['findings'])} findings",
        "Retention",
    ),
]
st.subheader("The seven claims, as the evidence stands")
_lib.table(
    [{"claim": r[0], "says": r[1], "evidence": r[2], "page": r[3]} for r in rows],
)
st.caption("The Gates page shows the other half: each gate is broken on purpose and must refuse it.")
