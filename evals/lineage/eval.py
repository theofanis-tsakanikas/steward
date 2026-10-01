"""Claim 3 — lineage reaches the dashboard, and every dashboard field resolves.

  A. clean estate: every dashboard reference (field, filter, sort) resolves to a catalogued column; every
     tagged column reaching a dashboard is masked for its model's connection role; LookML lineage equals
     the job history for every dashboard; every dashboard table traces back to a landing source
  B. drift (evals/lineage/drift/planted.yaml, applied in memory): exactly the planted blocking findings —
     an unresolved field; a sensitive column in clear on a dashboard even after an approved ceiling raise;
     a dashboard whose queries read a table its LookML does not show; a dashboard the history knows and
     LookML does not
Honest limits: the job history is a hand-written fixture written after the LookML, so the CLEAN agreement is
constructed — only the planted drift tests the cross-check; independence needs real Looker query jobs (a
Looker instance, D3; B18). LookML is parsed from files; no Looker instance is called.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

from steward import io, pipeline
from steward.core.findings import Finding, report

HERE = Path(__file__).resolve().parent


def history(extra_jobs: list | None = None) -> dict:
    h = json.loads((HERE / "query_history.json").read_text())
    return dict(h, jobs=h["jobs"] + (extra_jobs or []))


def run(contract_docs=None, roles_doc=None, lookml_root=None, hist=None):
    e = pipeline.load(contract_docs=contract_docs, roles_doc=roles_doc)
    lk, (findings, graph, detail) = pipeline.lineage(e, lookml_root or io.REPO / "lookml", hist or history())
    return lk, findings, graph, detail


def drift() -> tuple[list[Finding], list]:
    plan = yaml.safe_load((HERE / "drift" / "planted.yaml").read_text())
    docs = copy.deepcopy(io.contract_docs())
    docs["crm"]["tables"]["customers"]["columns"]["msisdn"]["masking"]["bi_service"] = plan["contract_patch"][
        "crm.customers.msisdn.masking.bi_service"
    ]
    roles = copy.deepcopy(io.roles_doc())
    roles["ceilings"]["bi_service"]["clear_kinds"] = plan["roles_patch"]["bi_service_clear_kinds"]
    roles["version"] += 1
    roles["changes"].append(plan["roles_patch"]["change"])
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "lookml"
        shutil.copytree(io.REPO / "lookml", root)
        for f in plan["lookml_extra_dashboards"]:
            shutil.copy(HERE / "drift" / f, root / "dashboards" / f)
        _, findings, _, _ = run(docs, roles, root, history(plan["jobs_extra"]))
    return findings, [tuple(x) for x in plan["expect"]]


def evaluate() -> dict:
    lk, findings, graph, detail = run()
    dfind, expect = drift()
    return {
        "lookml_mode": lk["mode"],
        "connections": {m: v["runs_as_role"] for m, v in lk["models"].items()},
        "counts": {
            "views": len(lk["views"]),
            "explores": len(lk["explores"]),
            "dashboards": len(lk["dashboards"]),
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
        },
        "clean_findings": [f.to_dict() for f in findings],
        "graph": graph.to_dict(),
        "detail": detail,
        "drift_expected": sorted(expect),
        "drift_got": sorted({(f.code, f.target) for f in dfind if f.blocking}),
        "drift_findings": [f.to_dict() for f in dfind],
        "history_mode": json.loads((HERE / "query_history.json").read_text())["_mode"],
    }


def main() -> int:
    r = evaluate()
    c = r["counts"]
    print(
        f"LookML ({r['lookml_mode']}): {c['views']} views, {c['explores']} explores, {c['dashboards']} dashboards; graph {c['nodes']} nodes, {c['edges']} edges; connections {r['connections']}"
    )
    code, lines = report("lineage (clean)", [Finding(**f) for f in r["clean_findings"]])
    print("\n".join("  " + ln for ln in lines))
    for d, chain in r["detail"]["paths"].items():
        print(f"  {d:18} ← " + " · ".join(f"{t} ← {', '.join(up) or '∅'}" for t, up in chain.items()))
    print(f"drift: expected {r['drift_expected']}")
    print(f"       got      {r['drift_got']}")
    for missing in sorted(set(map(tuple, r["drift_expected"])) - set(map(tuple, r["drift_got"]))):
        print(f"  NOT_DETECTED {missing[0]} {missing[1]}")
    for extra in sorted(set(map(tuple, r["drift_got"])) - set(map(tuple, r["drift_expected"]))):
        print(f"  UNEXPECTED {extra[0]} {extra[1]}")
    print(f"limit: {r['history_mode']}")
    ok = code == 0 and [list(x) for x in r["drift_got"]] == [list(x) for x in r["drift_expected"]]
    print(
        "ok claim 3: fields resolve, sensitive columns masked per role, lineage agrees with the job history and traces to a source; drift caught exactly"
        if ok
        else "FAIL claim 3"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
