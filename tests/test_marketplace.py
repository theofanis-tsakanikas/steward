import copy

import pytest

from steward import io, pipeline
from steward.core.lifecycle import states
from steward.core.marketplace import active_grants, decide, gate, load_ledger


@pytest.fixture(scope="module")
def e():
    return pipeline.load()


def _ledger():
    return copy.deepcopy(io.load_yaml(io.REPO / "marketplace" / "ledger.yaml"))


def outcome(e, ledger, rid):
    return next(o for o in decide(ledger, e.contracts, e.roles) if o.request["id"] == rid)


def codes(o):
    return sorted(r.code for r in o.reasons if r.severity == "error")


def test_group_approval_is_refused(e):
    lg = _ledger()
    lg["decisions"][0]["by"] = "group:network-owners@halverra.example"
    assert codes(outcome(e, lg, "R-001")) == ["APPROVER_NOT_HUMAN"]


def test_self_approval_is_caught_across_case_and_whitespace(e):
    lg = _ledger()
    lg["requests"][3]["requester"] = " user:Giorgos.Ioannou@halverra.example "
    assert "SELF_APPROVAL" in codes(outcome(e, lg, "R-004"))


def test_unknown_requester_and_wrong_seat_are_refused(e):
    lg = _ledger()
    lg["requests"][0]["requester"] = "user:nobody@evil.example"
    assert {"REQUESTER_UNKNOWN", "REQUESTER_NOT_IN_SEAT"} <= set(codes(outcome(e, lg, "R-001")))


def test_the_grant_goes_to_the_person_not_the_seat(e):
    grants = e.compiled["infra/marketplace/generated.tf.json"]["resource"]["google_bigquery_dataset_iam_member"]
    assert grants["r_001"]["member"] == '${var.grantees["user:eleni.kosta@halverra.example"]}'


def test_stale_decision_is_refused(e):
    lg = _ledger()
    lg["decisions"][0]["at"] = "2026-12-25T00:00:00Z"
    assert "DECISION_STALE" in codes(outcome(e, lg, "R-001"))


@pytest.mark.parametrize("bad", [{"days": 0}, {"days": -5}, {"days": 7.5}, {"days": "7"}])
def test_ledger_rejects_bad_days(bad):
    lg = _ledger()
    lg["requests"][0].update(bad)
    assert load_ledger(lg)[0] is None


def test_ledger_rejects_duplicates_and_orphan_decisions():
    lg = _ledger()
    lg["requests"].append(dict(lg["requests"][0]))
    assert load_ledger(lg)[0] is None
    lg = _ledger()
    lg["decisions"].append(
        {"request": "R-999", "decision": "approve", "by": "user:x@halverra.example", "at": "2026-09-30T00:00:00Z"}
    )
    assert load_ledger(lg)[0] is None


def test_an_invalid_ledger_grants_nothing():
    lg = _ledger()
    lg["requests"][0]["days"] = -1
    e2 = pipeline.load(ledger=lg)
    assert "google_bigquery_dataset_iam_member" not in e2.compiled["infra/marketplace/generated.tf.json"][
        "resource"
    ] or all(
        "condition" not in n
        for n in e2.compiled["infra/marketplace/generated.tf.json"]["resource"][
            "google_bigquery_dataset_iam_member"
        ].values()
    )
    assert e2.ledger_findings


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
    outs = decide(load_ledger(e.ledger)[0], e.contracts, e.roles)
    assert {o.request["id"] for o in active_grants(outs, "2026-09-01T00:00:00Z")} == {"R-001", "R-002", "R-009"}
    assert {o.request["id"] for o in active_grants(outs, "2026-12-01T00:00:00Z")} == set()


@pytest.mark.parametrize(
    "expr",
    [
        '!(request.time < timestamp("2026-10-09T15:00:00Z"))',
        'request.time < timestamp("garbage")',
        'request.time > timestamp("2026-10-09T15:00:00Z")',
    ],
)
def test_unrecognised_conditions_are_refused_not_parsed(e, expr):
    snap = {
        "captured_at": "2026-09-30T18:00:00Z",
        "bindings": [
            {
                "dataset": "network",
                "member": "user:eleni.kosta@halverra.example",
                "role": "roles/bigquery.dataViewer",
                "condition": {"expression": expr},
            }
        ],
    }
    out = {f.code for f in gate(snap, decide(e.ledger, e.contracts, e.roles), e.contracts, e.roles)}
    assert out == {"GRANT_CONDITION_UNRECOGNISED"}


def test_standing_reader_and_custodian_are_fine(e):
    snap = pipeline.iam_snapshot(e, "2026-09-30T18:00:00Z")
    assert any(b["member"] == "analyst@GR" and b["dataset"] == "crm" and not b["condition"] for b in snap["bindings"])
    assert [f for f in gate(snap, decide(e.ledger, e.contracts, e.roles), e.contracts, e.roles) if f.blocking] == []


def test_audit_dataset_has_a_contract_and_the_sink_targets_it(e):
    assert any(c.dataset == "audit" and c.log_sink for c in e.contracts)
    sink = e.compiled["infra/marketplace/generated.tf.json"]["resource"]["google_logging_project_sink"]["data_access"]
    assert sink["destination"].endswith("/datasets/audit")
    assert "audit" in e.compiled["infra/estate/generated.tf.json"]["resource"]["google_bigquery_dataset"]


def test_lifecycle_never_deletes_and_ignores_stale_notices():
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
            {
                "id": "d",
                "owner": "group:x@halverra.example",
                "last_viewed": "2026-06-01T00:00:00Z",
                "notified_at": "2026-01-01T00:00:00Z",
            },
        ],
    }
    got = {d["dashboard"]: d["state"] for d in states(usage)}
    assert got == {"a": "notify-owner", "b": "notify-owner", "c": "archive-due", "d": "notify-owner"}
    assert all("delete" not in d["state"] and "delete" not in d["action"] for d in states(usage))


@pytest.mark.parametrize(
    "role", ["projects/p/roles/readAll", "roles/owner", "roles/viewer", "roles/bigquery.dataOwner"]
)
def test_any_unexplained_role_is_flagged(e, role):
    snap = {
        "captured_at": "2026-09-30T18:00:00Z",
        "bindings": [{"dataset": "crm", "member": "analyst@IT", "role": role, "condition": None}],
    }
    assert {f.code for f in gate(snap, decide(e.ledger, e.contracts, e.roles), e.contracts, e.roles)} == {
        "GRANT_ROLE_UNEXPECTED"
    }


def test_only_the_captured_sink_writer_may_edit_audit(e):
    mine, foreign = (
        "serviceAccount:service-111@gcp-sa-logging.iam.gserviceaccount.com",
        "serviceAccount:service-999@gcp-sa-logging.iam.gserviceaccount.com",
    )
    snap = {
        "captured_at": "2026-09-30T18:00:00Z",
        "sink_writer_identity": mine,
        "bindings": [
            {"dataset": "audit", "member": mine, "role": "roles/bigquery.dataEditor", "condition": None},
            {"dataset": "audit", "member": foreign, "role": "roles/bigquery.dataEditor", "condition": None},
        ],
    }
    out = {(f.code, f.target) for f in gate(snap, decide(e.ledger, e.contracts, e.roles), e.contracts, e.roles)}
    assert out == {("GRANT_ROLE_UNEXPECTED", f"audit:{foreign}")}


def test_log_sink_is_not_a_key_for_an_ordinary_dataset():
    from datetime import date

    from steward.core.classify import detect
    from steward.core.gate_classification import gate as scan
    from steward.core.validate import validate_all

    docs = copy.deepcopy(io.contract_docs())
    del docs["audit"]
    net = docs["network"]
    net["log_sink"] = {"source": "pretend this is a sink", "personal_kinds": ["email"]}
    net["tables"] = {}
    net["readers"] = ["steward"]
    net["marketplace"].update(listable=False, grantable_roles=[])
    _, findings = validate_all(docs, io.roles_doc(), io.waivers_doc(), io.harvest(), date(2026, 10, 1))
    assert ("TABLE_UNDECLARED", "network.usage_events") in {(f.code, f.target) for f in findings if f.blocking}
    e2 = pipeline.load(contract_docs=docs)
    out = {
        (f.code, f.target)
        for f in scan(
            detect(io.synthetic_columns(), pipeline.synthetic_anchor()), e2.contracts, e2.compiled_tags, e2.broken
        )
        if f.blocking
    }
    assert ("PII_UNDECLARED_COLUMN", "network.usage_events.msisdn") in out


def test_log_sink_may_declare_only_email():
    docs = copy.deepcopy(io.contract_docs())
    docs["audit"]["log_sink"]["personal_kinds"] = ["msisdn"]
    from steward.core.validate import load_contract

    assert load_contract("audit", docs["audit"])[0] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("as_of", "garbage"),
        ("as_of", "2026-09-30T18:00:00"),
        ("requests.0.at", "2026-09-25 09:00"),
        ("requests.0.requester", "USER:eleni.kosta@halverra.example"),
    ],
)
def test_ledger_rejects_bad_times_and_prefixes(field, value):
    lg = _ledger()
    target = lg
    *path, last = field.split(".")
    for k in path:
        target = target[int(k)] if k.isdigit() else target[k]
    target[last] = value
    assert load_ledger(lg)[0] is None


def test_the_offline_snapshot_sees_marketplace_grants(e):
    snap = pipeline.iam_snapshot(e, "2026-09-30T18:00:00Z")
    assert any(b["member"] == "user:eleni.kosta@halverra.example" and b["condition"] for b in snap["bindings"])


def test_grantees_variable_is_declared_and_refuses_groups(e):
    var = e.compiled["infra/marketplace/generated.tf.json"]["variable"]["grantees"]
    assert any("never a group" in v["error_message"] for v in var["validation"])


def test_a_listing_names_its_approver_as_a_bare_address(e):
    """Analytics Hub refuses `mailto:...` as request_access: it must be an email address or a URL (first apply)."""
    listings = e.compiled["infra/marketplace/generated.tf.json"]["resource"]["google_bigquery_analytics_hub_listing"]
    assert listings
    for node in listings.values():
        assert "@" in node["request_access"] and not node["request_access"].startswith(("mailto:", "group:"))
