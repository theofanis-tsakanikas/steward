"""Catalog sync: generated payload, idempotency, reconciliation, mode."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st

import _lib

_lib.page(
    "Catalog sync (Collibra)",
    "Claim 4",
    "The catalog is generated from the contracts and the harvested estate, never typed. The mock the payload is "
    "sent to **validates every request against the documented Collibra shapes** and refuses what does not fit, "
    'so "it was accepted" means something.',
)
cat_doc = _lib.doc("catalog")
cat = cat_doc["data"]
sc = cat["scenarios"]
mode = cat["mode"]
(st.success if mode == "REAL" else st.warning)(
    f"Catalog mode: **{mode}**. "
    + (
        "A real instance accepted these requests."
        if mode == "REAL"
        else "No real Collibra instance was called; every statement below is about the validating mock."
    )
)

A = sc["A_clean"]
a, b, c = st.columns(3)
a.metric("First sync: changes sent", A["first"]["changes_sent"])
b.metric(
    "Second sync: changes sent", A["second"]["changes_sent"], help="idempotent: an unchanged estate changes nothing"
)
c.metric("Assets in the catalog", sum(A["assets_by_type"].values()))
_lib.mark("fixture", cat_doc)
st.bar_chart(pd.Series(A["assets_by_type"], name="assets"))

st.subheader("Reconciliation: GCP against the catalog")


def recon(r: dict) -> None:
    keys = [
        "in_gcp_not_in_catalog",
        "in_catalog_not_in_gcp",
        "in_catalog_not_generated",
        "generated_not_in_catalog",
        "pending_first_write",
    ]
    _lib.table(
        [{"list": k.replace("_", " "), "count": len(r[k]), "items": ", ".join(r[k])} for k in keys]
        + [
            {
                "list": "in both, differing",
                "count": len(r["in_both_differing"]),
                "items": ", ".join(str(x.get("resource", x)) for x in r["in_both_differing"]),
            }
        ]
    )
    st.caption(f"Reconciled at {r['reconciled_at']} (mode {r['mode']}).")


st.markdown("**Clean estate**")
recon(A["reconciliation"])
st.markdown(
    f"**After hand edits in the catalog** (ghost table, retired dashboard, changed owner, description, status, relation) — {sc['C_drift']['repair_commands']} commands repair it"
)
recon(sc["C_drift"]["reconciliation_before_repair"])
st.markdown("**Left over after the repair:** what Steward does not own is reported, never overwritten")
recon(sc["C_drift"]["after"])

st.subheader("What the mock refuses")
refusals = sc["B_refusals"]
_lib.table(
    [
        {
            "request": r["case"],
            "refused with": r["got"],
            "expected": r["expected"],
            "catalog untouched": r["catalog_untouched"],
        }
        for r in refusals
    ]
)
st.caption(
    f"{sum(r['got'] == r['expected'] and r['catalog_untouched'] for r in refusals)} of {len(refusals)} refused with the expected code and nothing written (atomic)."
)

st.subheader("When the sync fails")
f1 = sc["E_failure"]["first_failure"]
st.error(f"Simulated failure — {f1['status']}: {f1['error']}")
st.write("Stale marker written into the catalog: " + f"`{f1['stale']}`")
st.write("After the deadline: " + f"`{sc['E_failure']['second_failure']['stale']}`")
st.caption(
    "BigQuery keeps working; the documentation says it is stale, loudly, with its age (fail open on documentation, closed on privacy)."
)

st.subheader("A contract change is a new version; the catalog keeps the old words")
st.write(
    f"Changed: {', '.join(sc['D_contract_change']['changed'])} — history entries kept: {sc['D_contract_change']['history_entries']}"
)
st.subheader("What the sync leaves alone, or says")
st.write(sc["G_leave_alone_or_say"]["not_scanned"])
