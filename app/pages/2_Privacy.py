"""Privacy: personal data found by value, and the same query as three roles."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st

import _lib

_lib.page(
    "Privacy",
    "1 and 2",
    "The detector reads **values only** — the contract is never an input — so a column called `ref_2` that "
    "holds phone numbers is found. Then one query is run as three roles and gives three declared answers.",
)
cls = _lib.data("classification")
estate = _lib.data("estate")
declared = {c["column"]: c for d in estate["datasets"] for c in d["columns"]}

a, b, c, d = st.columns(4)
a.metric("Columns scanned", cls["n_columns"])
b.metric("Values scanned", f"{cls['n_values']:,}")
c.metric("Value detector recall", f"{cls['value_detector']['recall']:.0%}")
d.metric("Column names alone", f"{cls['name_heuristics']['recall']:.0%}", help="reported, never counted as proof")

rows = []
for det in cls["detections"]:
    col = declared.get(det["column"])
    rows.append(
        {
            "column": det["column"],
            "found by value": ", ".join(det["kinds"]),
            "values hit": sum(det["hits"].values()),
            "of": det["n_values"],
            "contract says": col["classification"] if col else "no contract — held at safe state (denied to all)",
            "agrees": "yes" if col and col["classification"] in ("personal", "special", "sensitive-network") else "no",
        }
    )
st.subheader("What the values say vs what the contract says")
_lib.table(rows)
st.caption(
    f"Innocent-named columns: the detector found {cls['innocent_columns']['detected']} of {cls['innocent_columns']['n']}; "
    f"the contract tags {cls['innocent_columns']['tagged_by_contract']}, and the other "
    f"{len(cls['innocent_columns']['held_at_safe_state_no_contract'])} sit in a dataset with no contract and are "
    "denied to every role."
)
st.warning(cls["limit"])

st.subheader("One query, three roles")
acc = _lib.data("access")
q = acc["query"]
st.code(q["sql"], language="sql")
st.caption(f"{q['mode']}. {q['note']}")
tabs = st.tabs([a["seat"] for a in q["answers"]])
for tab, ans in zip(tabs, q["answers"], strict=True):
    with tab:
        if "error" in ans:
            st.error(ans["error"])
            continue
        st.write(f"Row filter: `{ans['row_filter']}` — {ans['rows_visible']} of {ans['rows_total']} rows visible")
        st.write("Column treatment: " + ", ".join(f"`{c}` → {v}" for c, v in ans["access"].items()))
        _lib.table(ans["rows"])
st.write(
    f"The compiled controls were checked against the contracts for every seat and column: "
    f"{acc['checked_column_decisions']:,} column decisions, {acc['checked_row_filters']} row filters, "
    f"{len(acc['mismatches'])} mismatches, {len(acc['uncontracted_leaks'])} leaks from uncontracted columns."
)
st.info(
    "Not claimed offline: that BigQuery enforces them. Offline proves the compiled Terraform is what the "
    "contract implies; enforcement is captured live (three role transcripts) and re-checked here."
)
