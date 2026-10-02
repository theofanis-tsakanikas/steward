"""Shared by every page: read evidence (digest re-verified), say what mode it is, render tables.

No figure on a page is typed here or in a page: it is read from `evidence/` or computed from what is
read (scripts/check_demo_numbers.py refuses a literal that looks like a figure).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from steward import evidence


def source() -> str:
    """The offline fixture directory name. Live captures are a separate tree (`live()`)."""
    return evidence.FIXTURE


def live(name: str) -> dict | None:
    """A live capture's document (digest re-verified), or None when this repository holds none."""
    try:
        return evidence.load_live(name)
    except ValueError as ex:
        st.error(f"Live evidence refused: {ex}. Run `make evidence-check`.")
        st.stop()


def doc(name: str) -> dict:
    try:
        return evidence.load(source(), name)  # re-verified on every read: cheap, and never stale
    except FileNotFoundError:
        st.error(f"No evidence file `{source()}/{name}.json`. Run `make evidence` (and `make evidence-gates`).")
        st.stop()
    except ValueError as ex:  # digest mismatch: refuse to show what cannot be trusted
        st.error(f"Evidence refused: {ex}. Run `make evidence-check`.")
        st.stop()


def data(name: str) -> dict:
    return doc(name)["data"]


def when(document: dict) -> str:
    """That file's own date: a live capture's timestamp, else the fixture as-of day."""
    meta = document.get("meta") or {}
    return meta.get("captured_at") or meta.get("as_of") or "unknown"


def mark(origin: str, document: dict) -> None:
    """Visible under every figure: fixture or live, and that file's date — never a shared banner date."""
    label = "live capture · GCP estate" if origin == "live" else "offline fixture"
    st.caption(f"{label} · {when(document)}")


def collibra_mode() -> str:
    try:
        return doc("catalog")["data"]["mode"]
    except Exception:
        return "unknown"


def banner() -> None:
    mode = collibra_mode()
    what = (
        "a validating mock: no Collibra instance was called"
        if mode == "MOCK"
        else "a real Collibra instance"
        if mode == "REAL"
        else "unknown"
    )
    held = evidence.live_names()
    parts = []
    for name in held:
        try:
            d = evidence.load_live(name)
        except ValueError as ex:
            st.error(f"Live evidence refused: {ex}. Run `make evidence-check`.")
            st.stop()
        if d:
            parts.append(f"{name} {when(d)}")
    live_line = (
        f"**Live captures (GCP estate, then destroyed):** {'; '.join(parts)}  \n"
        if parts
        else "No live capture is held: pages show the offline fixture only.  \n"
    )
    st.info(
        "**Every figure is labelled** fixture (computed from this repository) or live (what the GCP estate answered).  \n"
        + live_line
        + f"**Collibra mode: {mode}** — {what}  \n"
        "Fictional operator (Halverra Telecom), synthetic data."
    )


def page(title: str, about: str, lead: str) -> None:
    st.set_page_config(page_title=f"Steward · {title}", layout="wide")
    banner()
    st.title(title)
    st.caption(about)
    if lead:
        st.markdown(lead)


def table(rows, columns: list[str] | None = None, **kw) -> None:
    frame = pd.DataFrame(rows)
    if columns:
        frame = frame[[c for c in columns if c in frame.columns]]
    st.dataframe(frame, hide_index=True, width="stretch", **kw)


def findings(rows) -> None:
    if not rows:
        st.success("No findings.")
        return
    table(rows, ["severity", "code", "target", "message"])


def access_transcripts(payload: dict) -> None:
    """One query, three roles, as BigQuery answered them."""
    rows = payload.get("transcripts") or []
    for qid in dict.fromkeys(t["query"] for t in rows):
        group = [t for t in rows if t["query"] == qid]
        st.code(group[0]["sql"], language="sql")
        sub = st.tabs([t["seat"] for t in group])
        for tab, t in zip(sub, group, strict=True):
            with tab:
                if t["outcome"] == "error":
                    st.error(f"Refused by BigQuery: {t.get('error', '')}")
                else:
                    st.write(f"{len(t['rows'])} row(s) returned · job `{t['job_id']}`")
                    table(t["rows"])
                if t.get("note"):
                    st.caption(t["note"])


def dataplex_scans(payload: dict) -> None:
    table(
        [
            {
                "scan": s["scan"],
                "state": s["state"],
                "rows scanned": s["rows_scanned"],
                "rule": r["rule"],
                "failed rows": r["failed_rows"],
                "passed": r["passed"],
            }
            for s in payload["scans"]
            for r in s["rules"]
        ]
    )


def iam_bindings(payload: dict) -> None:
    table([{**b, "condition": (b["condition"] or {}).get("expression", "—")} for b in payload["bindings"]])
    if payload.get("other_members"):
        st.markdown("Principals that are neither a seat nor a requester:")
        table(payload["other_members"])


def job_history(payload: dict) -> None:
    if payload.get("outcome") == "error":
        st.error(payload.get("error", ""))
        return
    table(payload["jobs"])
