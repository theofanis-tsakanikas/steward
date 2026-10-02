"""Lineage: source to table to LookML view to explore to dashboard, with the defects the gate catches."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st

import _lib

_lib.page(
    "Lineage",
    "Claim 3",
    "Edges come from BigQuery job metadata and from parsed LookML, and are cross-checked against each other. A "
    "dashboard field that resolves to no catalogued column, or a tagged column that reaches a dashboard unmasked "
    "for the connection's role, is a failing build.",
)
hist = _lib.live("history")
if hist:
    st.subheader("Job history from the estate")
    st.markdown(
        "BigQuery's own jobs for the estate's datasets, read as the deployer: which job wrote which table, as whom, "
        "reading what. Dashboard queries are not here: no Looker instance ran them."
    )
    _lib.job_history(hist["data"])
    _lib.mark("live", hist)

lin_doc = _lib.doc("lineage")
lin = lin_doc["data"]
cnt = lin["counts"]
a, b, c, d, e = st.columns(5)
a.metric("Views", cnt["views"])
b.metric("Explores", cnt["explores"])
c.metric("Dashboards", cnt["dashboards"])
d.metric("Graph nodes", cnt["nodes"])
e.metric("Graph edges", cnt["edges"])
_lib.mark("fixture", lin_doc)
st.caption(
    f"LookML: {lin['lookml_mode']} from files. Connections: "
    + ", ".join(f"{m} runs as {r}" for m, r in lin["connections"].items())
)

pick = st.selectbox("Dashboard", sorted(lin["detail"]["paths"]))
chain = lin["detail"]["paths"][pick]
st.write(
    "Traces back to a landing source: "
    + "; ".join(f"`{t}` ← {', '.join(f'`{u}`' for u in up)}" for t, up in chain.items())
)

colour = {
    "source": "lightgray",
    "table": "lightblue",
    "column": "aliceblue",
    "view": "palegreen",
    "explore": "khaki",
    "dashboard": "lightsalmon",
}
nodes = {n["id"]: n for n in lin["graph"]["nodes"]}
edges = lin["graph"]["edges"]
reach, frontier = {f"dashboard:{pick}"}, [f"dashboard:{pick}"]
while frontier:
    nxt = frontier.pop()
    for e_ in edges:
        if e_["to"] == nxt and e_["from"] not in reach:
            reach.add(e_["from"])
            frontier.append(e_["from"])
dot = ["digraph { rankdir=LR; node [shape=box, style=filled];"]
for nid in sorted(reach):
    n = nodes[nid]
    dot.append(f'"{nid}" [label="{n["label"]}", fillcolor="{colour.get(n["kind"], "white")}"];')
for e_ in edges:
    if e_["from"] in reach and e_["to"] in reach:
        style = "dashed" if e_["origin"] != "lookml" else "solid"
        dot.append(f'"{e_["from"]}" -> "{e_["to"]}" [style={style}, tooltip="{e_["origin"]}"];')
dot.append("}")
st.graphviz_chart("\n".join(dot), width="stretch")
st.caption("Solid: parsed from LookML. Dashed: from BigQuery job metadata.")

st.subheader("What each dashboard field is, and what the connection's role sees")
fields = [
    {
        "dashboard": dsh,
        "element": x["element"],
        "field": x["field"],
        "role": x["role"],
        "columns": ", ".join(x["columns"]),
        "as seen": ", ".join(f"{k.split('.')[-1]}: {v}" for k, v in x["as_seen"].items()),
    }
    for dsh, xs in lin["detail"]["dashboards"].items()
    for x in xs
    if dsh == pick
]
_lib.table(fields)

st.subheader("The clean estate")
_lib.findings(lin["clean_findings"])
st.subheader("Planted defects: each must be caught")
st.markdown(f"Expected {len(lin['drift_expected'])}, caught {len(lin['drift_got'])} — exactly the same set.")
_lib.findings(lin["drift_findings"])
st.warning(lin["history_mode"])
_lib.mark("fixture", lin_doc)
