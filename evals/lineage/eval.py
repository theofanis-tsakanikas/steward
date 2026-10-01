"""Claim 3 — lineage reaches the dashboard, and every dashboard field resolves.

  A. clean estate: every dashboard field resolves to a catalogued column; every tagged column that reaches
     a dashboard is masked for the Looker connection's role; LookML lineage equals the independent job
     history for every dashboard; every dashboard traces back to a landing source
  B. drift (evals/lineage/drift/planted.yaml, applied in memory): exactly the planted blocking findings —
     an unresolved field, a sensitive column in clear on a dashboard (even after an approved ceiling
     raise), and a dashboard whose queries read a table its LookML does not show
Honest limits: the job history is a hand-written fixture until T015 captures INFORMATION_SCHEMA.JOBS;
LookML is parsed from files, no Looker instance is called (D3).
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


def run(contract_docs=None, roles_doc=None, lookml_root=None, jobs=None):
    e = pipeline.load(contract_docs=contract_docs, roles_doc=roles_doc)
    jobs = jobs if jobs is not None else json.loads((HERE / "query_history.json").read_text())["jobs"]
    lk, (findings, graph, detail) = pipeline.lineage(e, lookml_root or io.REPO / "lookml", jobs)
    return lk, findings, graph, detail


def drift() -> tuple[list[Finding], list]:
    plan = yaml.safe_load((HERE / "drift" / "planted.yaml").read_text())
    docs = copy.deepcopy(io.contract_docs())
    col = docs["crm"]["tables"]["customers"]["columns"]["msisdn"]
    col["masking"]["bi_service"] = plan["contract_patch"]["crm.customers.msisdn.masking.bi_service"]
    roles = copy.deepcopy(io.roles_doc())
    roles["ceilings"]["bi_service"]["clear_kinds"] = plan["roles_patch"]["bi_service_clear_kinds"]
    roles["ceiling_changes"] = plan["roles_patch"]["ceiling_changes"]
    jobs = json.loads((HERE / "query_history.json").read_text())["jobs"] + plan["jobs_extra"]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "lookml"
        shutil.copytree(io.REPO / "lookml", root)
        for f in plan["lookml_extra_dashboards"]:
            shutil.copy(HERE / "drift" / f, root / "dashboards" / f)
        _, findings, _, _ = run(docs, roles, root, jobs)
    return findings, [tuple(x) for x in plan["expect"]]


def evaluate() -> dict:
    lk, findings, graph, detail = run()
    dfind, expect = drift()
    got = sorted({(f.code, f.target) for f in dfind if f.blocking})
    untraced = {
        d: [t for t, up in chain.items() if not any(n.startswith("source:") for n in up)]
        for d, chain in detail["paths"].items()
    }
    return {
        "lookml_mode": lk["mode"],
        "connection_role": lk["connection"]["runs_as_role"],
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
        "untraced": {d: t for d, t in untraced.items() if t},
        "drift_expected": sorted(expect),
        "drift_got": got,
        "drift_findings": [f.to_dict() for f in dfind],
    }


def main() -> int:
    r = evaluate()
    c = r["counts"]
    print(
        f"LookML ({r['lookml_mode']}): {c['views']} views, {c['explores']} explores, {c['dashboards']} dashboards; graph {c['nodes']} nodes, {c['edges']} edges; connection runs as {r['connection_role']}"
    )
    code, lines = report("lineage (clean)", [Finding(**f) for f in r["clean_findings"]])
    print("\n".join("  " + ln for ln in lines))
    for d, chain in r["detail"]["paths"].items():
        print(f"  {d:18} ← " + " · ".join(f"{t} ← {', '.join(up) or '∅'}" for t, up in chain.items()))
    for d, ts in r["untraced"].items():
        print(f"  UNTRACED {d}: {ts} has no path to a landing source")
    print(f"drift: expected {r['drift_expected']}")
    print(f"       got      {r['drift_got']}")
    for missing in sorted(set(map(tuple, r["drift_expected"])) - set(map(tuple, r["drift_got"]))):
        print(f"  NOT_DETECTED {missing[0]} {missing[1]}")
    for extra in sorted(set(map(tuple, r["drift_got"])) - set(map(tuple, r["drift_expected"]))):
        print(f"  UNEXPECTED {extra[0]} {extra[1]}")
    ok = code == 0 and not r["untraced"] and [list(x) for x in r["drift_got"]] == [list(x) for x in r["drift_expected"]]
    print(
        "ok claim 3: fields resolve, sensitive columns masked on dashboards, lineage agrees with job history; drift caught exactly"
        if ok
        else "FAIL claim 3"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
