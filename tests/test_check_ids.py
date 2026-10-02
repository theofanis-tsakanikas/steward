"""The ids gate reads identifiers from tfvars/env and refuses a tree that contains them — never the other way."""

from __future__ import annotations

import importlib.util

from steward import io


def _load():
    spec = importlib.util.spec_from_file_location("check_ids", io.REPO / "scripts" / "check_ids.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ids = _load()


def test_placeholders_and_short_values_are_not_identifiers(tmp_path):
    tf = tmp_path / "terraform.tfvars"
    tf.write_text(
        'project_id = "CHANGE-ME"\nbilling_account_id = "000000-000000-000000"\n'
        'github_owner_id = "0"\nalert_emails = ["you@example.com"]\n'
    )
    assert ids.identifiers(env={}, tfvars=tf, extra=()) == set()


def test_tfvars_and_env_supply_identifiers_and_never_github_owner(tmp_path):
    tf = tmp_path / "terraform.tfvars"
    tf.write_text(
        'project_id = "steward-demo-000000"\nproject_number = "999000111222"\n'
        'org_id = "888000111222"\nbilling_account_id = "AAAAAA-BBBBBB-CCCCCC"\n'
        'github_owner = "someone"\ngithub_repo = "steward"\n'
        'alert_emails = ["owner@example.net"]\n'
    )
    got = ids.identifiers(env={"STEWARD_PROJECT_ID": "from-env-project"}, tfvars=tf, extra=())
    assert "steward-demo-000000" in got and "999000111222" in got and "888000111222" in got
    assert "AAAAAA-BBBBBB-CCCCCC" in got and "owner@example.net" in got and "from-env-project" in got
    assert "someone" not in got and "steward" not in got


def test_a_planted_id_in_the_tree_is_named_without_repeating_the_id(tmp_path):
    leak = tmp_path / "leak.txt"
    leak.write_text("service-999000111222@gcp-sa-logging.iam.gserviceaccount.com\n")
    found = ids.hits(tmp_path, {"999000111222"}, files=[leak])
    assert found == ["leak.txt"]
    msg = f"ERROR ID_IN_TREE {found[0]} — a project/org/billing identifier from terraform.tfvars or the environment"
    assert "999000111222" not in msg


def test_the_committed_gate_has_no_extra_ids():
    assert ids.EXTRA_IDS == ()
