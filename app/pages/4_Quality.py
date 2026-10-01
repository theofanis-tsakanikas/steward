"""Data quality: rules from contracts, quarantine with the rule id, source = loaded + quarantined."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st

import _lib

_lib.page(
    "Data quality",
    "5",
    "Rules live in the contract. A failing row goes to a quarantine table with its rule id, row key and run id "
    "and is routed to the dataset's owner — it is never dropped. The source count is taken **before** the rules "
    "run, so the reconciliation cannot be trivially true.",
)
q = _lib.data("quality")
rows = []
for t, c in q["counts"].items():
    rows.append(
        {
            "table": t,
            "source": c["source"],
            "loaded": c["loaded"],
            "quarantined": c["quarantined"],
            "source = loaded + quarantined": "yes" if c["source"] == c["loaded"] + c["quarantined"] else "NO",
        }
    )
_lib.table(rows)
a, b, c = st.columns(3)
a.metric("Failures planted in the sources", q["planted"])
b.metric("Missed", len(q["missed"]))
c.metric("Quarantined but not planted", len(q["unexpected"]))

left, right = st.columns(2)
with left:
    st.subheader("Quarantined rows by rule")
    st.bar_chart(pd.Series(q["by_rule"], name="rows"))
with right:
    st.subheader("Routed to")
    st.bar_chart(pd.Series(q["routed_to"], name="rows"))

st.subheader("The quarantine table")
_lib.table(
    [
        {
            "table": r["table"],
            "row key": r["row_key"],
            "rule": ", ".join(r["rule_ids"]),
            "why": "; ".join(f"{f['column']}: {f['reason']}" for f in r["failures"]),
            "run id": r["run_id"],
            "routed to owner": r["routed_to"],
            "steward": r["steward"],
        }
        for r in q["quarantine_sample"]
    ]
)
_lib.findings(q["findings"])
