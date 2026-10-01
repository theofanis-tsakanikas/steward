"""Claim 1 — no sensitive column is unclassified.

Three parts, each printed with its n:
  A. the value detector vs the planted manifest (column × kind), incl. the innocent-named columns
  B. name heuristics on the same columns — reported, never counted as proof
  C. hand-labelled hard cases (formats the generator never emits; look-alikes that are not PII)
and the gate itself on the committed contracts, which must be green.

Honest limit printed with the result: the generator and the detector were written by the same author,
so A measures that the pipeline and the gate work end to end — not detector quality in the wild.
T014 compares the same samples against Google Sensitive Data Protection.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import yaml

from steward import io, pipeline

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import load_planted
from steward.core.classify import detect, name_heuristics, scan_value
from steward.core.findings import Finding, report
from steward.core.gate_classification import gate

HERE = Path(__file__).resolve().parent


def _score(pred: set, truth: set) -> dict:
    tp, fp, fn = len(pred & truth), len(pred - truth), len(truth - pred)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(tp / (tp + fp), 4) if tp + fp else 1.0,
        "recall": round(tp / (tp + fn), 4) if tp + fn else 1.0,
        "false_positives": sorted(map(list, pred - truth)),
        "false_negatives": sorted(map(list, truth - pred)),
    }


def evaluate() -> dict:
    planted = load_planted()
    scan_date = date.fromisoformat(planted["anchor_date"])
    columns = io.synthetic_columns()
    detections = detect(columns, scan_date)

    truth = {(p["column"], k) for p in planted["pii"] for k in p["kinds"]}
    innocent_cols = {p["column"] for p in planted["pii"] if p["planted_in_innocent_column"]}
    by_value = {(d.column, k) for d in detections for k in d.kinds}
    by_name = {(c, k) for c in columns for k in name_heuristics(c)}

    cases = yaml.safe_load((HERE / "cases.yaml").read_text())
    case_results = []

    def kinds_of(v):
        return {k for k in scan_value(v, scan_date) if not k.startswith("_")}

    for c in cases["positives"]:
        got = kinds_of(c["value"])
        case_results.append(
            {"value": c["value"], "expected": sorted(c["kinds"]), "got": sorted(got), "ok": got == set(c["kinds"])}
        )
    for c in cases["negatives"]:
        got = kinds_of(c["value"])
        case_results.append({"value": c["value"], "expected": [], "got": sorted(got), "ok": not got})
    for c in cases["fifteen_digit"]:
        sig = kinds_of(c["value"])
        got = "imei" if "imei" in sig else "imsi" if "imsi" in sig else "none"
        case_results.append({"value": c["value"], "expected": [c["expect"]], "got": [got], "ok": got == c["expect"]})

    e = pipeline.load()
    findings = gate(detections, e.contracts, e.compiled_tags, e.broken)
    flagged_innocent = {d.column for d in detections if d.kinds and d.column in innocent_cols}
    held = {f.target for f in findings if f.code == "PII_HELD_AT_SAFE_STATE"}

    return {
        "scan_date": scan_date.isoformat(),
        "n_columns": len(columns),
        "n_values": sum(len([v for v in vals if v is not None]) for vals in columns.values()),
        "n_truth_pairs": len(truth),
        "value_detector": _score(by_value, truth),
        "value_detector_innocent_columns": _score(
            {p for p in by_value if p[0] in innocent_cols}, {p for p in truth if p[0] in innocent_cols}
        ),
        "name_heuristics": _score(by_name, truth),
        "name_heuristics_innocent_columns": _score(
            {p for p in by_name if p[0] in innocent_cols}, {p for p in truth if p[0] in innocent_cols}
        ),
        "innocent_columns": {
            "n": len(innocent_cols),
            "detected": len(flagged_innocent),
            "tagged_by_contract": len(flagged_innocent - held),
            "held_at_safe_state_no_contract": sorted(held & innocent_cols),
        },
        "hard_cases": {"n": len(case_results), "passed": sum(r["ok"] for r in case_results), "results": case_results},
        "detections": [d.to_dict() for d in detections if d.kinds],
        "gate_findings": [f.to_dict() for f in findings],
        "limit": "generator and detector share an author: part A is a pipeline check (the planted PII reaches the gate), not a measure of detection in the wild; C is the independent part (see T014 for Google DLP on the same samples)",
    }


def main() -> int:
    r = evaluate()
    v, vi, nm, nmi = (
        r["value_detector"],
        r["value_detector_innocent_columns"],
        r["name_heuristics"],
        r["name_heuristics_innocent_columns"],
    )
    print(
        f"scanned {r['n_columns']} columns, {r['n_values']} non-null values; ground truth {r['n_truth_pairs']} column×kind pairs"
    )
    print(
        f"A value detector      precision {v['precision']:.3f}  recall {v['recall']:.3f}   (tp {v['tp']} fp {v['fp']} fn {v['fn']})"
    )
    print(
        f"  innocent-named only precision {vi['precision']:.3f}  recall {vi['recall']:.3f}   (tp {vi['tp']} fp {vi['fp']} fn {vi['fn']})"
    )
    print(f"B name heuristics     precision {nm['precision']:.3f}  recall {nm['recall']:.3f}   — reported, not proof")
    print(f"  innocent-named only                    recall {nmi['recall']:.3f}   ← what a name-based scan misses")
    ic = r["innocent_columns"]
    print(
        f"  innocent-named columns: {ic['detected']}/{ic['n']} detected; {ic['tagged_by_contract']} tagged by a contract, "
        f"{len(ic['held_at_safe_state_no_contract'])} held at `restricted` with no contract (legacy, waiver W-001)"
    )
    hc = r["hard_cases"]
    print(f"C hard cases          {hc['passed']}/{hc['n']} correct")
    for c in hc["results"]:
        if not c["ok"]:
            print(f"    MISS {c['value']!r}: expected {c['expected']} got {c['got']}")
    code, lines = report("classification", [Finding(**f) for f in r["gate_findings"]])
    print("\n".join("  " + ln for ln in lines))
    print(f"limit: {r['limit']}")
    failed = []
    if v["recall"] < 1.0:
        failed.append("recall < 1.0 on planted PII")
    if v["precision"] < 0.95:
        failed.append("precision < 0.95")
    if hc["passed"] != hc["n"]:
        failed.append("hard cases")
    if code:
        failed.append("gate red on committed contracts")
    if failed:
        print("FAIL claim 1: " + "; ".join(failed))
        return 1
    print("ok claim 1: every planted PII column found by value, and the gate is green on the committed contracts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
