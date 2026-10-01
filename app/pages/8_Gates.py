"""Gates: every gate, the mutation that breaks it, and the refusal."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st

import _lib

_lib.page(
    "Gates",
    "all",
    "Each gate is broken on purpose, and the **named** gate must refuse it, for the right reason. Three rules: "
    "green first; a non-zero exit is not evidence (the finding line must carry the expected code and target); a "
    "mutation whose target has moved is STALE, not passed.",
)
doc = _lib.doc("gates")
g = doc["data"]
res = g["results"]
refused = sum(r["status"] == "REFUSED" for r in res)
a, b, c = st.columns(3)
a.metric("Mutations", len(res))
b.metric("Refused by the named gate", refused)
c.metric("Not refused", len(res) - refused)
(st.success if refused == len(res) else st.error)(
    "Every mutation was refused by its named gate." if refused == len(res) else "Some mutation was not refused."
)
st.caption(
    "Rules: " + " · ".join(g["rules"]) + f". Recorded from `scripts/gate_proof.py`, as of {doc['meta']['as_of']}."
)
st.caption(
    "The recorded run leaves out the gate that checks the record itself (`evidence`); CI runs its mutations on "
    "every push."
)
gates = sorted({r["gate"] for r in res})
pick = st.multiselect("Gate", gates, default=gates)
_lib.table(
    [
        {
            "gate": r["gate"],
            "claim": r["claim"],
            "what was broken": r["name"],
            "why it must refuse": r["why"],
            "expected": f"{r['expect'][0]} · {r['expect'][1]}",
            "result": r["status"],
            "the gate said": r["detail"],
        }
        for r in res
        if r["gate"] in pick
    ]
)
