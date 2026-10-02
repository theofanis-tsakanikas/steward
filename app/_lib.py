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
    """The offline fixture: every page's figures. Live captures are shown beside it (`live()`), never instead of it."""
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


def collibra_mode() -> str:
    try:
        return doc("catalog")["data"]["mode"]
    except Exception:
        return "unknown"


def banner() -> None:
    src = source()
    try:
        as_of = doc("estate")["meta"]["as_of"]
    except Exception:
        as_of = "unknown"
    mode = collibra_mode()
    what = (
        "a validating mock: no Collibra instance was called"
        if mode == "MOCK"
        else "a real Collibra instance"
        if mode == "REAL"
        else "unknown"
    )
    captured = evidence.live_names()
    live_line = (
        f"**Live captures held: {', '.join(captured)}** — see the Live estate page  \n"
        if captured
        else "No live capture is held: everything shown is the offline fixture  \n"
    )
    st.info(
        f"**RECORDED mode** · evidence `{src}` (offline fixture, computed from the repository) · data as of {as_of}  \n"
        + live_line
        + f"**Collibra mode: {mode}** — {what}  \n"
        "Fictional operator (Halverra Telecom), synthetic data."
    )


def page(title: str, claim: str, lead: str) -> None:
    st.set_page_config(page_title=f"Steward · {title}", layout="wide")
    banner()
    st.title(title)
    st.caption(f"Claim {claim}")
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
