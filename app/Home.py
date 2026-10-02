"""Steward — landing page: what this is, and the one-line state of each claim, from evidence."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import streamlit as st

import _lib

_lib.page(
    "Steward",
    "Seven claims · each figure is labelled fixture or live, with that file's date",
    "A governance layer for a telco's BigQuery estate. **A column that holds personal data without a policy "
    "tag, an owner and a retention period is a build failure**, and the catalog is generated from the estate, "
    "never hand-maintained. Live captures are what the GCP estate answered; the fixture is computed offline "
    "from this repository. Digests are re-checked when a page opens.",
)

estate_doc = _lib.doc("estate")
estate = estate_doc["data"]
cls_doc = _lib.doc("classification")
cls = cls_doc["data"]
acc_doc = _lib.doc("access")
acc = acc_doc["data"]
lin_doc = _lib.doc("lineage")
lin = lin_doc["data"]
qual_doc = _lib.doc("quality")
qual = qual_doc["data"]
cat_doc = _lib.doc("catalog")
cat = cat_doc["data"]["scenarios"]
mkt_doc = _lib.doc("marketplace")
mkt = mkt_doc["data"]
ret_doc = _lib.doc("retention")
ret = ret_doc["data"]
dlp = _lib.live("dlp")
acc_live = _lib.live("access")
dp_live = _lib.live("dataplex")
iam_live = _lib.live("iam")
hist_live = _lib.live("history")

columns = [c for d in estate["datasets"] for c in d["columns"]]
tagged = [c for c in columns if c["masking"]]
quarantined = sum(v["quarantined"] for v in qual["counts"].values())
refused = sum(1 for o in mkt["outcomes"] if o["status"] != "granted")

a, b, c, d = st.columns(4)
a.metric("Contracted datasets", len(estate["datasets"]))
b.metric("Declared columns", len(columns), f"{len(tagged)} carry a policy tag")
c.metric("Columns scanned by value", cls["n_columns"], f"{cls['n_values']:,} values")
d.metric("Catalog assets", sum(cat["A_clean"]["assets_by_type"].values()))
_lib.mark("fixture", estate_doc)
st.caption(f"Value scan · {_lib.when(cls_doc)} (fixture). Catalog · {_lib.when(cat_doc)} (fixture).")

claim_1 = (
    f"value detector found {cls['value_detector']['tp']} of {cls['n_truth_pairs']} planted (column, kind) pairs; "
    f"names alone found {cls['name_heuristics']['tp']}"
)
if dlp:
    claim_1 += (
        f" · DLP inspected {len(dlp['data']['tables'])} tables, "
        f"{len(dlp['data']['findings'])} finding(s) in untagged columns"
    )

if acc_live:
    seats = sorted({t["seat"] for t in acc_live["data"]["transcripts"]})
    claim_2 = (
        f"{len(acc_live['data']['transcripts'])} BigQuery transcripts across {len(seats)} seats "
        f"(compiled check: {acc['checked_column_decisions']:,} seat × column, {len(acc['mismatches'])} mismatches)"
    )
    claim_2_src = "live"
    claim_2_when = _lib.when(acc_live)
else:
    claim_2 = (
        f"{acc['checked_column_decisions']:,} seat × column decisions checked against the contracts, "
        f"{len(acc['mismatches'])} mismatches"
    )
    claim_2_src = "fixture"
    claim_2_when = _lib.when(acc_doc)

if hist_live:
    jobs = hist_live["data"].get("jobs") or []
    claim_3 = (
        f"{lin['counts']['nodes']} nodes, {lin['counts']['edges']} edges, {lin['counts']['dashboards']} dashboards "
        f"(fixture); {len(jobs)} jobs in the estate history"
    )
else:
    claim_3 = (
        f"{lin['counts']['nodes']} nodes, {lin['counts']['edges']} edges, {lin['counts']['dashboards']} dashboards; "
        f"{len(lin['drift_got'])} planted defects caught"
    )

if dp_live:
    scans = dp_live["data"].get("scans") or []
    claim_5 = (
        f"{len(scans)} Dataplex scan(s) on the estate; "
        f"{quarantined} rows quarantined by the offline engine across {len(qual['counts'])} tables"
    )
    claim_5_src = "live"
    claim_5_when = _lib.when(dp_live)
else:
    claim_5 = (
        f"{quarantined} rows quarantined across {len(qual['counts'])} tables; "
        f"{len(qual['missed'])} planted failures missed"
    )
    claim_5_src = "fixture"
    claim_5_when = _lib.when(qual_doc)

if iam_live:
    claim_6 = (
        f"{len(iam_live['data']['bindings'])} IAM bindings captured on the estate; "
        f"{len(mkt['outcomes'])} fixture requests "
        f"({len(mkt['outcomes']) - refused} granted, {refused} not)"
    )
    claim_6_src = "live"
    claim_6_when = _lib.when(iam_live)
else:
    claim_6 = f"{len(mkt['outcomes'])} requests: {len(mkt['outcomes']) - refused} granted, {refused} not"
    claim_6_src = "fixture"
    claim_6_when = _lib.when(mkt_doc)

rows = [
    {
        "claim": "1",
        "says": "No sensitive column is unclassified",
        "evidence": claim_1,
        "shows": "live" if dlp else "fixture",
        "as of": _lib.when(dlp) if dlp else _lib.when(cls_doc),
        "page": "Privacy",
    },
    {
        "claim": "2",
        "says": "Same query, different answer, by role",
        "evidence": claim_2,
        "shows": claim_2_src,
        "as of": claim_2_when,
        "page": "Privacy",
    },
    {
        "claim": "3",
        "says": "Lineage reaches the dashboard",
        "evidence": claim_3,
        "shows": "live" if hist_live else "fixture",
        "as of": _lib.when(hist_live) if hist_live else _lib.when(lin_doc),
        "page": "Lineage",
    },
    {
        "claim": "4",
        "says": "The catalog is generated, idempotent, reconciled",
        "evidence": (
            f"first sync sent {cat['A_clean']['first']['changes_sent']}, second sent "
            f"{cat['A_clean']['second']['changes_sent']}; mode {cat['A_clean']['first']['mode']}"
        ),
        "shows": "fixture",
        "as of": _lib.when(cat_doc),
        "page": "Catalog",
    },
    {
        "claim": "5",
        "says": "A failing row is quarantined, never dropped",
        "evidence": claim_5,
        "shows": claim_5_src,
        "as of": claim_5_when,
        "page": "Quality",
    },
    {
        "claim": "6",
        "says": "Access is requested, approved by a named human, and expires",
        "evidence": claim_6,
        "shows": claim_6_src,
        "as of": claim_6_when,
        "page": "Marketplace",
    },
    {
        "claim": "7",
        "says": "Retention is declared, enforced and evidenced",
        "evidence": f"{len(ret['report']['rows'])} tables reported; {len(ret['findings'])} findings",
        "shows": "fixture",
        "as of": _lib.when(ret_doc),
        "page": "Retention",
    },
]
st.subheader("The seven claims, as the evidence stands")
_lib.table(rows)
st.caption("The Gates page shows the other half: each gate is broken on purpose and must refuse it.")
