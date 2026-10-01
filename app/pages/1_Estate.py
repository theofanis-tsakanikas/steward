"""Estate and contracts: who owns what, what every column is classified as, what is waived."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st

import _lib

_lib.page(
    "Estate & contracts",
    "1, 4, 7",
    "One YAML contract per dataset is the source of truth: owner, steward, custodian, retention with its legal "
    "basis, and a classification for every column. Everything else on these pages is generated from them.",
)
estate = _lib.data("estate")
ds = estate["datasets"]

_lib.table(
    [
        {
            "dataset": d["dataset"],
            "version": d["version"],
            "owner": d["owner"],
            "steward": d["steward"],
            "custodian": d["custodian"],
            "retention (days)": d["retention_days"],
            "listed in marketplace": d["listable"],
            "tables": ", ".join(d["tables"]) or f"(log sink: {d['log_sink']})",
        }
        for d in ds
    ]
)

st.subheader("Classification coverage")
cols = pd.DataFrame([c | {"dataset": c["column"].split(".")[0]} for d in ds for c in d["columns"]])
pivot = cols.groupby(["dataset", "classification"]).size().unstack(fill_value=0)
st.bar_chart(pivot)
tagged = cols[cols["masking"].map(bool)]
st.write(
    f"{len(tagged)} of {len(cols)} declared columns carry a policy tag; "
    f"{int((cols['classification'] == 'public').sum())} are classified public — and nobody gets `public` by default: "
    "a column with no declaration fails the build."
)

st.subheader("Columns")
pick = st.selectbox("Dataset", [d["dataset"] for d in ds])
view = cols[cols["dataset"] == pick]
view = view.assign(masking=view["masking"].map(lambda m: ", ".join(f"{r}: {v}" for r, v in m.items())))
view = view.assign(quality_rules=view["quality_rules"].map(", ".join), kinds=view["kinds"].map(", ".join))
_lib.table(view, ["column", "type", "classification", "kinds", "masking", "quality_rules"])
basis = next(d for d in ds if d["dataset"] == pick)
st.caption(f"Lawful basis: {basis['lawful_basis']}  \nRetention basis: {basis['retention_basis']}")

st.subheader("Not under contract")
st.markdown(
    "A dataset with no contract is not ignored: its columns are held at the safe state (denied to every role) "
    "until an owner declares them. A waiver for that has an owner-approved expiry date."
)
_lib.table(estate["waivers"], ["id", "finding", "target", "approved_by", "expires", "reason"])
st.write(f"Columns in the estate no contract declares: {len(estate['uncontracted_columns'])}")
st.code("\n".join(estate["uncontracted_columns"]))
