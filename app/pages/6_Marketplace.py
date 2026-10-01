"""Data Marketplace: request, named approval, grant with expiry, expired grant flagged."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st

import _lib

_lib.page(
    "Data Marketplace",
    "6",
    "A request becomes an IAM grant only after a decision by a named human who is not the requester and not a "
    "service account. Every grant carries an expiry (an IAM Condition). An expired grant still present turns CI red.",
)
m = _lib.data("marketplace")
st.subheader("Requests and their outcomes")
_lib.table(
    [
        {
            "request": o["request"]["id"],
            "requester": o["request"]["requester"],
            "dataset": o["request"]["dataset"],
            "asked as": o["request"]["seat"],
            "days": o["request"]["days"],
            "approved by": (o["decision"] or {}).get("by", "—"),
            "outcome": o["status"],
            "expires": o["expires_at"] or "—",
            "why not": "; ".join(f"{r['code']}" for r in o["reasons"]),
        }
        for o in m["outcomes"]
    ]
)
for o in m["outcomes"]:
    for r in o["reasons"]:
        st.caption(f"{o['request']['id']} · {r['code']}: {r['message']}")

st.subheader("The estate's IAM, judged at the capture time")
st.write(f"Snapshot captured {m['captured_at']} — {m['clean_snapshot']['source']}")
st.write(f"Bindings: {len(m['clean_snapshot']['bindings'])}; findings on the clean estate: {len(m['clean_findings'])}.")
st.markdown("**Planted: each must be caught by the gate**")
got = {tuple(x) for x in m["drift_got"]}
_lib.table(
    [
        {
            "member": p["member"],
            "dataset": p["dataset"],
            "expected finding": p["expect"],
            "caught": "yes" if any(g[0] == p["expect"] and p["member"] in g[1] for g in got) else "NO",
            "why": p["why"],
        }
        for p in m["drift_planted"]
    ]
)
st.caption(
    f'"Now" is the evidence capture time, not the checker\'s clock: judged at {m["now_from_evidence"]["early_capture"]} '
    f"the same snapshot flags an expired grant: {m['now_from_evidence']['expired_flagged_early']}."
)

st.subheader("Unused dashboards: the expiry workflow")
life = m["lifecycle"]
st.warning(life["mode"])
_lib.table(life["dashboards"])
