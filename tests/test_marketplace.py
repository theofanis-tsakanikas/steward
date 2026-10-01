import ast
import copy
from pathlib import Path

import pytest

from steward import io, pipeline
from steward.core.lifecycle import states
from steward.core.marketplace import active_grants, decide, gate

ROOT = Path(__file__).resolve().parent.parent


def test_no_clock_is_read():
    """Claim 6's trap: the evaluator takes now from evidence. No now()/today()/time() call in these modules."""
    for mod in ("marketplace.py", "lifecycle.py", "compile_marketplace.py"):
        tree = ast.parse((ROOT / "src/steward/core" / mod).read_text())
        calls = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        assert not {"now", "today", "utcnow", "time"} & set(calls), mod


@pytest.fixture
def e():
    return pipeline.load()


def _ledger():
    return copy.deepcopy(io.load_yaml(io.REPO / "marketplace" / "ledger.yaml"))


def outcome(e, ledger, rid):
    return next(o for o in decide(ledger, e.contracts, e.roles) if o.request["id"] == rid)


def test_group_approval_is_refused(e):
    lg = _ledger()
    lg["decisions"][0]["by"] = "group:network-owners@halverra.example"
    assert [r.code for r in outcome(e, lg, "R-001").reasons] == ["APPROVER_NOT_HUMAN"]


def test_two_decisions_are_ambiguous(e):
    lg = _ledger()
    lg["decisions"].append(dict(lg["decisions"][0]))
    assert outcome(e, lg, "R-001").status == "refused"


def test_denial_is_honoured(e):
    lg = _ledger()
    lg["decisions"][0]["decision"] = "deny"
    assert outcome(e, lg, "R-001").status == "refused"


def test_expired_grants_are_not_compiled(e):
    gov = e.compiled["infra/marketplace/generated.tf.json"]["resource"]["google_bigquery_dataset_iam_member"]
    assert "r_009" not in gov and "r_001" in gov and "r_002" in gov
    assert gov["r_001"]["condition"]["expression"] == 'request.time < timestamp("2026-10-09T15:00:00Z")'


def test_active_grants_follow_as_of_not_a_clock(e):
    outs = decide(e.ledger, e.contracts, e.roles)
    assert {o.request["id"] for o in active_grants(outs, "2026-09-01T00:00:00Z")} == {"R-001", "R-002", "R-009"}
    assert {o.request["id"] for o in active_grants(outs, "2026-12-01T00:00:00Z")} == set()


def test_standing_reader_without_condition_is_fine(e):
    snap = pipeline.iam_snapshot(e, "2026-09-30T18:00:00Z")
    assert any(b["seat"] == "analyst@GR" and b["dataset"] == "crm" and not b["condition"] for b in snap["bindings"])
    assert [f for f in gate(snap, decide(e.ledger, e.contracts, e.roles), e.contracts, e.roles) if f.blocking] == []


def test_lifecycle_never_deletes_and_waits_for_grace():
    usage = {
        "captured_at": "2026-09-30T00:00:00Z",
        "dashboards": [
            {"id": "a", "owner": "group:x@halverra.example", "last_viewed": "2026-06-01T00:00:00Z"},
            {
                "id": "b",
                "owner": "group:x@halverra.example",
                "last_viewed": "2026-06-01T00:00:00Z",
                "notified_at": "2026-09-25T00:00:00Z",
            },
            {
                "id": "c",
                "owner": "group:x@halverra.example",
                "last_viewed": "2026-06-01T00:00:00Z",
                "notified_at": "2026-09-01T00:00:00Z",
            },
        ],
    }
    got = {d["dashboard"]: d["state"] for d in states(usage)}
    assert got == {"a": "notify-owner", "b": "notify-owner", "c": "archive-due"}
    assert not any(d["delete"] for d in states(usage))
