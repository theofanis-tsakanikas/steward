"""The doctrine-4 script against a real throwaway git repository — the fail-closed paths."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ccv", ROOT / "scripts" / "check_contract_versions.py")
ccv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ccv)


def sh(repo, *a):
    subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.delenv("STEWARD_BASE_REF", raising=False)
    r = tmp_path / "r"
    shutil.copytree(ROOT / "contracts", r / "contracts")
    sh(r, "init", "-q", "-b", "main")
    sh(r, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    sh(r, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    return r


def edit(repo, bump: bool):
    p = repo / "contracts" / "crm.yaml"
    doc = yaml.safe_load(p.read_text())
    doc["tables"]["support_tickets"]["columns"]["ref_2"]["description"] = "changed"
    if bump:
        doc["version"] += 1
        doc["changelog"].append({"version": doc["version"], "date": "2026-10-02", "change": "describe ref_2"})
    p.write_text(yaml.safe_dump(doc))


def test_unbumped_change_fails(repo):
    edit(repo, bump=False)
    assert ccv.main(["--base", "main"], repo=repo) == 1


def test_bumped_change_passes(repo):
    edit(repo, bump=True)
    assert ccv.main(["--base", "main"], repo=repo) == 0


@pytest.mark.parametrize("base", ["deadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "no-such-ref"])
def test_explicit_unresolvable_base_fails(repo, base):
    assert ccv.main(["--base", base], repo=repo) == 1


def test_all_zero_base_compares_with_previous_commit(repo):
    edit(repo, bump=False)
    sh(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "unbumped")
    assert ccv.main(["--base", "0" * 40], repo=repo) == 1


def test_env_base_is_explicit(repo, monkeypatch):
    monkeypatch.setenv("STEWARD_BASE_REF", "origin/gone")
    assert ccv.main([], repo=repo) == 1
