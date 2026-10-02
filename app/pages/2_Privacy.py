"""Privacy: personal data found by value, and the same query as three roles."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st

import _lib

_lib.page(
    "Privacy",
    "Claims 1 and 2",
    "The detector reads **values only** — the contract is never an input — so a column called `ref_2` that "
    "holds phone numbers is found. Then one query is run as three roles and gives three declared answers. "
    "When a live capture exists, BigQuery's own transcripts are shown first.",
)
cls_doc = _lib.doc("classification")
cls = cls_doc["data"]
estate = _lib.data("estate")
declared = {c["column"]: c for d in estate["datasets"] for c in d["columns"]}

a, b, c, d = st.columns(4)
a.metric("Columns scanned", cls["n_columns"])
b.metric("Values scanned", f"{cls['n_values']:,}")
c.metric("Value detector recall", f"{cls['value_detector']['recall']:.0%}")
d.metric("Column names alone", f"{cls['name_heuristics']['recall']:.0%}", help="reported, never counted as proof")
_lib.mark("fixture", cls_doc)

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
_lib.mark("fixture", cls_doc)

dlp = _lib.live("dlp")
if dlp:
    st.subheader("What Sensitive Data Protection found on the estate")
    payload = dlp["data"]
    st.markdown(
        f"Inspected {len(payload['tables'])} tables with template `{payload['template']}` in `{payload['region']}`. "
        f"{payload['method']}."
    )
    _lib.table(
        [
            {
                "table": t["table"],
                "read as": t["read_as"],
                "rows read": t["rows_read"],
                "of": t["sample"]["num_rows"],
                "columns scanned": len(t["columns_scanned"]),
                "not scanned": len(t["columns_not_scanned"]),
                "truncated": t["truncated"],
            }
            for t in payload["tables"]
        ]
    )
    st.markdown(f"**Findings in columns the contracts leave untagged: {len(payload['findings'])}**")
    _lib.table(payload["findings"])
    ctl = payload["control"]
    st.markdown(
        f"**Control** — the same template over the generator's own rows ({ctl['rows_per_table']} per table, "
        "every column), so that an empty answer above cannot be a blind detector."
    )
    _lib.table(ctl["findings"], ["table", "column", "info_type", "kind", "rows_with_a_finding"])
    _lib.mark("live", dlp)

st.subheader("One query, three roles")
acc_live = _lib.live("access")
if acc_live:
    st.info(
        "These rows came back from BigQuery as each seat's service account. A masked column is hashed, "
        "nullified, last-four or a default — not the stored value."
    )
    _lib.access_transcripts(acc_live["data"])
    _lib.mark("live", acc_live)
else:
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
    _lib.mark("fixture", _lib.doc("access"))

acc_doc = _lib.doc("access")
acc = acc_doc["data"]
st.write(
    f"Offline, the compiled controls were checked against the contracts for every seat and column: "
    f"{acc['checked_column_decisions']:,} column decisions, {acc['checked_row_filters']} row filters, "
    f"{len(acc['mismatches'])} mismatches, {len(acc['uncontracted_leaks'])} leaks from uncontracted columns."
)
_lib.mark("fixture", acc_doc)
st.info(
    "Not claimed from the fixture: that BigQuery enforces them. The transcripts above are the live capture; "
    "they are re-judged on the Live estate page with no account."
)
