"""Evidence: what the demo reads, and the gate that keeps it honest.

    evidence/<source>/<name>.json   {"meta": {...digest...}, "data": {...}}
    evidence/MANIFEST.json          every file and its digest

`<source>` is `fixture` (computed offline from the repository: contracts, the synthetic estate, the claim
harnesses' own results) or `live` (captured from a running estate, T012+). The demo reads one source and
says which. Outside `core/`: it reads files and runs the harnesses; every verdict in it was reached by a
core function.

`check()` is the gate (EVIDENCE_*): a file whose digest does not match its payload was edited by hand;
a fixture file that differs from what the repository produces today is stale; `gates.json` — a recorded
gate-proof run, too slow to recompute here — must still list exactly today's mutations, all refused.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from steward import io
from steward.core.findings import Finding

ROOT = io.REPO / "evidence"
FIXTURE = "fixture"
SOURCES = (FIXTURE, "live")
GATES_FILE = "gates"
# The recorded gate-proof run omits the gate that checks the record: it cannot vouch for itself (CI runs it).
SELF_CHECKING = frozenset({"evidence"})
SCHEMA = 1

# name -> (claim, one line saying where the payload comes from)
FAST: dict[str, tuple[str, str]] = {
    "estate": ("1,4,7", "contracts/*.yaml, loaded and validated by core.contract"),
    "classification": ("1", "evals/classification/eval.py evaluate()"),
    "access": ("2", "evals/access/eval.py evaluate()"),
    "lineage": ("3", "evals/lineage/eval.py evaluate()"),
    "quality": ("5", "evals/quality/eval.py evaluate()"),
    "catalog": ("4", "evals/catalog/eval.py evaluate()"),
    "marketplace": ("6", "evals/marketplace/eval.py evaluate()"),
    "retention": ("7", "evals/retention/eval.py evaluate()"),
}


def canonical(data) -> str:
    return json.dumps(data, sort_keys=True, indent=1, ensure_ascii=False, default=_plain) + "\n"


def _plain(o):
    if isinstance(o, set | frozenset):
        return sorted(o)
    if isinstance(o, tuple):
        return list(o)
    return str(o)


def digest(data) -> str:
    return hashlib.sha256(canonical(data).encode()).hexdigest()


_CHILD = """
import contextlib, importlib.util, io, json, sys
name = sys.argv[1]
path = sys.argv[2] + "/evals/" + name + "/eval.py"
sys.path.insert(0, sys.argv[2] + "/evals")  # evals/_common.py
spec = importlib.util.spec_from_file_location("evidence_eval_" + name, path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
with contextlib.redirect_stdout(io.StringIO()):  # a harness prints its table; the payload is what it returns
    result = mod.evaluate()
def plain(o):
    return sorted(o) if isinstance(o, (set, frozenset)) else list(o) if isinstance(o, tuple) else str(o)
sys.stdout.write(json.dumps(result, default=plain))
"""


def _evaluate(name: str) -> dict:
    """One claim harness's `evaluate()`, in its own process: the planted ground truth is read by evals only,
    and an eval run in-process from here would put that read inside a production import path."""
    r = subprocess.run(
        [sys.executable, "-c", _CHILD, name, str(io.REPO)],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(io.REPO / "src")},
        cwd=io.REPO,
    )
    if r.returncode:
        raise RuntimeError(f"evals/{name}/eval.py evaluate() failed:\n{r.stderr[-1500:]}")
    return json.loads(canonical(json.loads(r.stdout)))


def estate() -> dict:
    from steward import pipeline

    e = pipeline.load()
    datasets = []
    for c in sorted(e.contracts, key=lambda c: c.dataset):
        cols = [
            {
                "column": fqn,
                "table": t,
                "type": col.type,
                "classification": str(col.classification),
                "kinds": sorted(col.kinds),
                "masking": {k: str(v) for k, v in sorted(col.masking.items())},
                "quality_rules": [r.id for r in col.quality],
            }
            for fqn, t, _path, col in c.iter_columns()
        ]
        datasets.append(
            {
                "dataset": c.dataset,
                "version": c.version,
                "description": c.description,
                "owner": c.owner,
                "steward": c.steward,
                "custodian": c.custodian,
                "lawful_basis": c.lawful_basis,
                "retention_days": c.retention.period_days,
                "retention_basis": c.retention.legal_basis,
                "readers": sorted(c.readers),
                "listable": c.marketplace.listable,
                "log_sink": c.log_sink.source if c.log_sink else None,
                "tables": sorted(c.tables),
                "columns": cols,
            }
        )
    waivers = [
        {k: str(w.get(k)) for k in ("id", "finding", "target", "reason", "approved_by", "expires")}
        for w in io.waivers_doc().get("waivers", [])
    ]
    uncontracted = sorted(
        f"{t}.{f['name']}"
        for t, spec in e.harvest.items()
        if t.split(".")[0] not in {c.dataset for c in e.contracts}
        for f in spec["fields"]
    )
    return {
        "operator": "Halverra Telecom (fictional)",
        "datasets": datasets,
        "waivers": waivers,
        "uncontracted_columns": uncontracted,
    }


def build_fast() -> dict[str, dict]:
    out = {}
    for name in FAST:
        out[name] = estate() if name == "estate" else _evaluate(name)
    return out


def anchor() -> str:
    from steward import pipeline

    return pipeline.synthetic_anchor().isoformat()


def wrap(name: str, data, source: str, claim: str, origin: str, extra: dict | None = None) -> dict:
    return {
        "meta": {
            "schema": SCHEMA,
            "name": name,
            "claim": claim,
            "mode": source,
            "operator": "fictional (Halverra Telecom)",
            "data": "synthetic",
            "origin": origin,
            "as_of": anchor(),
            "digest": digest(data),
            **(extra or {}),
        },
        "data": data,
    }


def build_files() -> dict[str, dict]:
    return {
        name: wrap(name, data, FIXTURE, FAST[name][0], FAST[name][1]) for name, data in sorted(build_fast().items())
    }


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical(doc))


def write_manifest() -> None:
    files = {}
    for src in SOURCES:
        for p in sorted((ROOT / src).glob("*.json")) if (ROOT / src).is_dir() else []:
            files[f"{src}/{p.name}"] = json.loads(p.read_text())["meta"]["digest"]
    _write(ROOT / "MANIFEST.json", {"schema": SCHEMA, "files": files})


def write_fixture() -> list[str]:
    docs = build_files()
    for name, doc in docs.items():
        _write(ROOT / FIXTURE / f"{name}.json", doc)
    write_manifest()
    return sorted(docs)


def record_gates(results_json: Path) -> None:
    """Wrap a `gate_proof.py --json` run as evidence. Recorded, not recomputed: it takes minutes."""
    raw = json.loads(results_json.read_text())
    doc = wrap(
        GATES_FILE,
        raw,
        FIXTURE,
        "all",
        "scripts/gate_proof.py --json",
        {"recorded": True},
    )
    _write(ROOT / FIXTURE / f"{GATES_FILE}.json", doc)
    write_manifest()


def load(source: str, name: str) -> dict:
    """The payload of one evidence file, after its digest has been re-verified."""
    doc = json.loads((ROOT / source / f"{name}.json").read_text())
    if digest(doc["data"]) != doc["meta"]["digest"]:
        raise ValueError(f"evidence/{source}/{name}.json: the payload does not match its digest")
    return doc


def live_names() -> list[str]:
    """The live captures committed under evidence/live/ (a subset of what the capture can write)."""
    d = ROOT / "live"
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def load_live(name: str) -> dict | None:
    """One live capture, digest re-verified; None when it was never captured."""
    return load("live", name) if name in live_names() else None


# ── the gate ──────────────────────────────────────────────────────────────────────────────────────


def _gate_names() -> set[tuple[str, str, str, str]]:
    spec = importlib.util.spec_from_file_location("evidence_gate_proof", io.REPO / "scripts" / "gate_proof.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # @dataclass resolves its own module
    spec.loader.exec_module(mod)
    return {(m.gate, m.name, m.marker[0], m.marker[1]) for m in mod.MUTATIONS if m.gate not in SELF_CHECKING}


def check() -> list[Finding]:
    out: list[Finding] = []

    def f(code: str, target: str, msg: str) -> None:
        out.append(Finding(code, "evidence", target, msg))

    manifest_path = ROOT / "MANIFEST.json"
    if not manifest_path.exists():
        return [Finding("EVIDENCE_MISSING", "evidence", "MANIFEST.json", "run `make evidence`")]
    manifest = json.loads(manifest_path.read_text())["files"]
    seen: dict[str, str] = {}
    for src in SOURCES:
        for p in sorted((ROOT / src).glob("*.json")) if (ROOT / src).is_dir() else []:
            rel = f"{src}/{p.name}"
            try:
                doc = json.loads(p.read_text())
                meta, data = doc["meta"], doc["data"]
            except (ValueError, KeyError) as ex:
                f("EVIDENCE_MALFORMED", rel, f"not an evidence document: {ex}")
                continue
            if digest(data) != meta.get("digest"):
                f("EVIDENCE_DIGEST_MISMATCH", rel, "the payload does not match its recorded digest: edited by hand?")
            if meta.get("mode") != src:
                f("EVIDENCE_MODE_MISMATCH", rel, f"sits under {src}/ but says mode={meta.get('mode')!r}")
            seen[rel] = meta.get("digest", "")
    for rel, dg in seen.items():
        if manifest.get(rel) != dg:
            f("EVIDENCE_UNLISTED", rel, "not in MANIFEST.json with this digest: run `make evidence`")
    for rel in sorted(set(manifest) - set(seen)):
        f("EVIDENCE_MISSING", rel, "listed in MANIFEST.json, not on disk")
    for name in FAST:
        if f"{FIXTURE}/{name}.json" not in seen:
            f("EVIDENCE_MISSING", f"{FIXTURE}/{name}.json", "the demo reads it: run `make evidence`")
    # the fixture is a function of the repository: recompute it and compare
    for name, doc in build_files().items():
        rel = f"{FIXTURE}/{name}.json"
        if rel in seen and seen[rel] == doc["meta"]["digest"]:
            continue
        if rel in seen:
            f("EVIDENCE_STALE", rel, "the repository now produces different evidence: run `make evidence`")
    # the recorded gate-proof run: shape, and still today's mutations
    gp = ROOT / FIXTURE / f"{GATES_FILE}.json"
    if not gp.exists():
        f("EVIDENCE_MISSING", f"{FIXTURE}/{GATES_FILE}.json", "run `make evidence-gates` (minutes: it runs gate-proof)")
    elif f"{FIXTURE}/{GATES_FILE}.json" in seen:
        rec = json.loads(gp.read_text())["data"]
        bad = [r for r in rec.get("results", []) if r.get("status") != "REFUSED"]
        for r in bad:
            f("GATES_NOT_REFUSED", f"{r.get('gate')}: {r.get('name')}", f"recorded as {r.get('status')}")
        have = {(r["gate"], r["name"], r["expect"][0], r["expect"][1]) for r in rec.get("results", [])}
        want = _gate_names()
        if have != want:
            drift = sorted(have ^ want)
            f(
                "GATES_STALE",
                GATES_FILE,
                f"the recorded gate-proof run and MUTATIONS disagree on {len(drift)} entr{'y' if len(drift) == 1 else 'ies'}"
                f" (first: {drift[0][0]}: {drift[0][1]}): run `make evidence-gates`",
            )
    return out
