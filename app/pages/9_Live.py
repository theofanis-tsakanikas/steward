"""Live estate: what a running BigQuery answered, captured once and re-judged here, offline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import streamlit as st

import _lib
from steward import live as live_checks

_lib.page(
    "Live estate",
    "1, 2, 5 and 6",
    "Everything above this page is computed offline. This page shows what the **deployed** estate answered: three "
    "roles running one query, Sensitive Data Protection over the data, Dataplex quality scans, the IAM policy and the "
    "audit trail. Each capture was written by `steward capture`; here it is **judged again by code, with no account**, "
    "against what the contracts and the compiled Terraform say it must be.",
)

NAMES = ("access", "dlp", "dataplex", "iam", "audit")
held = {n: _lib.live(n) for n in NAMES}
if not any(held.values()):
    st.warning(
        "This repository holds no live capture yet. The estate is deployed, captured and destroyed in one session; "
        "run `make capture` against a deployed estate to fill this page."
    )
    st.stop()

e = None


def verdict(name: str, d: dict):
    global e
    from steward import pipeline

    e = e or pipeline.load()
    found = live_checks.VERIFY[name](d["data"], e)
    blocking = [f for f in found if f.blocking]
    meta = d["meta"]
    st.caption(f"captured {meta['captured_at']} · {meta['origin']} · digest `{meta['digest'][:12]}`")
    if blocking:
        st.error(f"{len(blocking)} blocking finding(s) when this capture is re-judged offline")
    else:
        st.success("Re-judged offline: every check passes")
    _lib.findings([{"severity": f.severity, "code": f.code, "target": f.target, "message": f.message} for f in found])


tabs = st.tabs([n for n in NAMES if held[n]])
for tab, name in zip(tabs, [n for n in NAMES if held[n]], strict=True):
    d = held[name]
    data = d["data"]
    with tab:
        verdict(name, d)
        if name == "access":
            st.markdown(
                "One query, run as each seat's service account. A column the seat may not read in clear comes back "
                "**masked by BigQuery** (hash, nullified, last four, default value); a table the seat may not read is "
                "refused. `LIVE_VALUE_NOT_MASKED` fires if a masked column ever equals the stored value."
            )
            for qid in dict.fromkeys(t["query"] for t in data["transcripts"]):
                group = [t for t in data["transcripts"] if t["query"] == qid]
                st.code(group[0]["sql"], language="sql")
                sub = st.tabs([t["seat"] for t in group])
                for st_tab, t in zip(sub, group, strict=True):
                    with st_tab:
                        if t["outcome"] == "error":
                            st.error(f"Refused by BigQuery: {t.get('error', '')}")
                        else:
                            st.write(f"{len(t['rows'])} row(s) returned · job `{t['job_id']}`")
                            _lib.table(t["rows"])
                        if t.get("note"):
                            st.caption(t["note"])
        elif name == "dlp":
            st.markdown(
                f"Sensitive Data Protection inspected {len(data['tables'])} tables with template "
                f"`{data['template']}` in `{data['region']}`. {data['method']}."
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
                    for t in data["tables"]
                ]
            )
            st.markdown(f"**Findings in columns the contracts leave untagged: {len(data['findings'])}**")
            _lib.table(data["findings"])
            ctl = data["control"]
            st.markdown(
                f"**Control** — the same template over the generator's own rows ({ctl['rows_per_table']} per table, "
                "every column), so that an empty answer above cannot be a blind detector."
            )
            _lib.table(ctl["findings"], ["table", "column", "info_type", "kind", "rows_with_a_finding"])
        elif name == "dataplex":
            st.markdown(
                "On-demand data-quality scans compiled from the contracts, each run as the dataset's custodian seat. "
                "Failed rows per rule are compared with the rows the offline engine quarantined."
            )
            _lib.table(
                [
                    {
                        "scan": s["scan"],
                        "state": s["state"],
                        "rows scanned": s["rows_scanned"],
                        "rule": r["rule"],
                        "failed rows": r["failed_rows"],
                        "passed": r["passed"],
                    }
                    for s in data["scans"]
                    for r in s["rules"]
                ]
            )
        elif name == "iam":
            st.markdown(
                "The dataset IAM policies as BigQuery holds them (policy version 3, so IAM Conditions are present). "
                "A grant that carries an expiry is a binding with a condition."
            )
            _lib.table([{**b, "condition": (b["condition"] or {}).get("expression", "—")} for b in data["bindings"]])
            if data["other_members"]:
                st.markdown("Principals that are neither a seat nor a requester:")
                _lib.table(data["other_members"])
        elif name == "audit":
            st.markdown(
                "The access review: who ran queries lately, read from the audit sink as the audit dataset's steward."
            )
            if data["outcome"] == "error":
                st.error(data.get("error", ""))
            else:
                _lib.table(data["rows"])
