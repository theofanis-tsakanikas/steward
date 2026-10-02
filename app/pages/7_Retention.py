"""Retention: declared, compiled, evidenced - with the time-travel caveat first."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st

import _lib

_lib.page("Retention", "Claim 7", "")
r_doc = _lib.doc("retention")
r = r_doc["data"]
st.warning(r["report"]["caveat"])
rows = r["report"]["rows"]
_lib.table(
    [
        {
            "dataset": x["dataset"],
            "table": x["table"],
            "period (days)": x.get("period_days") or "—",
            "mechanism": x["mechanism"]["kind"],
            "column": x.get("column") or "—",
            "status": x["status"],
            "legal basis": x.get("legal_basis") or "—",
        }
        for x in rows
    ]
)
st.write(f"{len(rows)} tables reported; {len(r['findings'])} findings.")
st.caption("A dataset with no retention period fails the build; there is no default period.")
_lib.mark("fixture", r_doc)
_lib.findings(r["findings"])
