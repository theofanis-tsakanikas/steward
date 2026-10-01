"""Claim 4's parts: the REAL client (against a fake HTTP session — nothing is called), the CLI, the directory,
and the independence of the builder's vocabulary from the mock's model."""

from __future__ import annotations

import json

import pytest

from steward import catalog_sync as S
from steward import cli, pipeline
from steward.adapters.collibra.client import CollibraClient
from steward.adapters.collibra.mock import MockCollibra, Rejection
from steward.core import catalog as C


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def json(self):
        return self.body


class FakeHttp:
    def __init__(self, job_state):
        self.job_state = job_state
        self.posts = []

    def post(self, url, files=None, data=None, timeout=None):
        self.posts.append((url, files, data))
        return FakeResponse({"id": "job-1"})

    def get(self, url, timeout=None):
        return FakeResponse(self.job_state, getattr(self, "poll_status", 200))


def client_with(job_state) -> tuple[CollibraClient, FakeHttp]:
    c = CollibraClient.__new__(CollibraClient)
    c.base = "https://example.collibra.invalid"
    c.http = FakeHttp(job_state)
    return c, c.http


def test_real_client_states_every_import_parameter_explicitly():
    c, http = client_with({"state": "COMPLETED", "result": "SUCCESS"})
    out = c.import_job([{"resourceType": "Community", "identifier": {"name": "x"}}], "2026-10-01T00:00:00Z")
    (url, files, data) = http.posts[0]
    assert url.endswith("/rest/2.0/import/json-job")
    # the default of continueOnError changed in Collibra 2026.07: a partial import must never look like success
    assert data["continueOnError"] == "false"
    assert data["relationsAction"] == data["attributesAction"] == "REPLACE"
    assert out["mode"] == "REAL" and out["job"] == "job-1"
    assert json.loads(files["file"][1])[0]["resourceType"] == "Community"


@pytest.mark.parametrize(
    "state",
    [
        {"state": "COMPLETED", "result": "COMPLETED_WITH_ERROR", "message": "1 command failed"},
        {"state": "COMPLETED", "result": "ABORTED"},
        {"state": "ERROR", "result": "FAILURE"},
        {"state": "CANCELED", "result": ""},
        {"state": "COMPLETED"},  # no result at all is not success
        {"state": "COMPLETED_WITH_ERROR"},  # the guide does not say whether this is the state or the result
        {"state": "ABORTED"},
    ],
)
def test_real_client_only_completed_success_is_a_sync(state):
    c, _ = client_with(state)
    with pytest.raises(RuntimeError):
        c.import_job([], "2026-10-01T00:00:00Z")


def test_real_read_back_is_not_pretended():
    c, _ = client_with({})
    with pytest.raises(NotImplementedError):
        c.current()


def test_cli_real_mode_sends_nothing_and_says_why(capsys, tmp_path):
    state = tmp_path / "s.json"
    assert cli.main(["sync", "--mode", "real", "--state", str(state)]) == 2
    assert "REAL mode needs a Collibra trial" in capsys.readouterr().out
    assert not state.exists()


def test_cli_sync_twice_changes_nothing_and_logs_the_runs(capsys, tmp_path):
    state = tmp_path / "s.json"
    assert cli.main(["sync", "--state", str(state), "--at", "2026-10-01T09:00:00Z"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert cli.main(["sync", "--state", str(state), "--at", "2026-10-01T09:05:00Z"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert first["changes_sent"] == first["created"] > 0
    assert second["changes_sent"] == 0 and second["mode"] == "MOCK"
    runs = json.loads(state.read_text())["runs"]
    assert [r["run_at"] for r in runs] == ["2026-10-01T09:00:00Z", "2026-10-01T09:05:00Z"]
    assert cli.main(["reconcile", "--state", str(state), "--at", "2026-10-01T09:06:00Z"]) == 0


def test_every_group_a_contract_names_has_a_user_group_id():
    e = pipeline.load()
    directory = S.model()["user_groups"]
    named = {g for c in e.contracts for g in (c.owner, c.steward, c.custodian)}
    assert named <= set(directory), sorted(named - set(directory))
    assert len(set(directory.values())) == len(directory), "two groups share an id"


def test_the_builders_relations_are_each_declared_by_the_model():
    """The builder's constants and the mock's model are written separately; if they disagree the mock refuses."""
    model = {
        f"{r['source']}:{r['source_role']}:{r['target_role']}:{r['target']}:TARGET" for r in S.model()["relation_types"]
    }
    assert {C.IS_PART_OF_TABLE, C.IS_PART_OF_SCHEMA, C.USES_COLUMN, C.REPRESENTED_BY} == model


def test_no_responsibilities_on_assets_and_none_invented_for_uncontracted_datasets():
    cmds = S.desired(pipeline.load())
    assert not [c for c in cmds if c["resourceType"] == "Asset" and "responsibilities" in c]
    legacy = next(c for c in cmds if c["resourceType"] == "Domain" and c["identifier"]["name"].startswith("legacy"))
    assert "responsibilities" not in legacy  # no contract, no owner to name (doctrine 3)


def test_an_unsent_attribute_is_not_a_removed_one():
    """The Import API leaves attributes a command omits; the mock does too, so the builder never omits."""
    cl = MockCollibra(S.model())
    cl.import_job(S.desired(pipeline.load()), "2026-10-01T09:00:00Z")
    col = next(c for c in S.desired(pipeline.load()) if c["resourceType"] == "Asset" and c["type"]["name"] == "Column")
    trimmed = json.loads(json.dumps(col))
    del trimmed["attributes"]["Masking"]
    cl.import_job([trimmed], "2026-10-01T09:01:00Z")
    stored = cl.current()[C.key(col)]
    assert "Masking" in stored["attributes"]


def test_relations_are_replaced_by_type_and_an_empty_list_deletes():
    cl = MockCollibra(S.model())
    cmds = S.desired(pipeline.load())
    cl.import_job(cmds, "2026-10-01T09:00:00Z")
    report = next(c for c in cmds if c["resourceType"] == "Asset" and c["type"]["name"] == "Report")
    assert report["relations"][C.USES_COLUMN]
    emptied = json.loads(json.dumps(report))
    emptied["relations"][C.USES_COLUMN] = []
    cl.import_job([emptied], "2026-10-01T09:01:00Z")
    assert cl.current()[C.key(report)]["relations"][C.USES_COLUMN] == []


def test_a_refusal_names_the_command_that_failed():
    cl = MockCollibra(S.model())
    cmds = S.desired(pipeline.load())
    i = next(i for i, c in enumerate(cmds) if c["resourceType"] == "Asset")
    cmds[i]["status"] = {"name": "Approved"}
    with pytest.raises(Rejection) as exc:
        cl.import_job(cmds, "2026-10-01T09:00:00Z")
    assert exc.value.code == "UNKNOWN_STATUS" and exc.value.command == i
    assert cl.current() == {}


def test_real_client_does_not_poll_an_error_page_until_the_timeout():
    c, http = client_with({"state": "COMPLETED", "result": "SUCCESS"})
    http.poll_status = 401
    with pytest.raises(RuntimeError, match="401"):
        c.import_job([], "2026-10-01T00:00:00Z")


def test_real_report_does_not_claim_counts_it_does_not_have():
    class Real:
        mode = "REAL"

        def current(self):
            return {}

        def import_job(self, commands, at):
            return {"mode": "REAL", "job": "j"}  # no counts until the read-back exists

    rep = S.sync(Real(), pipeline.load(), "2026-10-01T09:00:00Z")
    assert rep["status"] == "ok" and rep["created"] is None and rep["updated"] is None


def test_a_build_failure_is_a_logged_failed_run_not_a_traceback(monkeypatch):
    cl = MockCollibra(S.model())
    groups = {k: v for k, v in S.model()["user_groups"].items() if k != "group:crm-owners@halverra.example"}
    real = S.desired
    monkeypatch.setattr(S, "desired", lambda est, mode="MOCK", group_ids=None: real(est, mode, groups))
    rep = S.sync(cl, pipeline.load(), "2026-10-01T09:00:00Z")
    assert rep["status"] == "failed" and rep["error"].startswith("OWNER_GROUP_UNKNOWN")
    assert cl.state["runs"][-1]["status"] == "failed"
