import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_core_purity", ROOT / "scripts" / "check_core_purity.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_core_is_pure():
    assert mod.violations() == []


def test_purity_check_bites(tmp_path):
    core = tmp_path / "core"
    core.mkdir()
    (core / "bad.py").write_text("from google.cloud import bigquery\nimport json\n")
    # rel path computation needs the file under REPO; emulate by pointing REPO at tmp
    mod.REPO = tmp_path
    try:
        found = mod.violations(core)
    finally:
        mod.REPO = ROOT
    assert len(found) == 1 and "google.cloud" in found[0]
