"""The planted ground truth is read by evals only — proved at runtime, not by grepping source.

Every production path (load, validate, compile, scan, gate) runs under an audit hook that records every
file opened. Building the path from pieces, globbing or reading through another module cannot dodge
it: the hook sees the final `open`.
"""

import sys
from datetime import date

from steward import io, pipeline
from steward.core.classify import detect
from steward.core.compile import check
from steward.core.gate_classification import gate
from steward.core.validate import validate_all

opened: list[str] = []


def _hook(event, args):
    if event == "open" and args and isinstance(args[0], str | bytes):
        opened.append(str(args[0]))


sys.addaudithook(_hook)


def test_production_paths_never_open_the_ground_truth():
    opened.clear()
    validate_all(io.contract_docs(), io.roles_doc(), io.waivers_doc(), io.harvest(), date(2026, 10, 1))
    e = pipeline.load()
    check(e.contracts, e.roles)
    e.rendered()
    gate(detect(io.synthetic_columns(), pipeline.synthetic_anchor()), e.contracts, e.compiled_tags, e.broken)
    assert opened, "the hook saw nothing — it is not wired"
    leaks = [p for p in opened if "ground_truth" in p or "planted" in p]
    assert leaks == []


def test_the_hook_would_see_a_leak():
    opened.clear()
    (io.REPO / "evals" / "ground_truth" / "planted.json").read_text()
    assert any("planted" in p for p in opened)
