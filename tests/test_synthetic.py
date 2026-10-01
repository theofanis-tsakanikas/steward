import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from synthetic import generate as g  # noqa: E402


def test_two_runs_are_byte_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for out in (a, b):
        subprocess.run([sys.executable, str(ROOT / "synthetic/generate.py"), "--out", str(out)], check=True)
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    assert files
    for rel in files:
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel


def test_committed_output_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "synthetic/generate.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


def _rows(table):
    return [json.loads(line) for line in (ROOT / f"synthetic/data/{table}.jsonl").read_text().splitlines()]


def test_check_digits_are_real():
    def iban_ok(s):
        s = s[4:] + s[:4]
        return int("".join(str(int(c, 36)) for c in s)) % 97 == 1

    assert all(iban_ok(r["iban"]) for r in _rows("finance.billing"))
    assert all(g.luhn_digit(r["imei"][:-1]) == r["imei"][-1] for r in _rows("network.network_events"))


def test_schema_matches_rows():
    schema = json.loads((ROOT / "synthetic/data/_schema.json").read_text())
    for table, spec in schema.items():
        names = {f["name"] for f in spec["fields"]}
        for row in _rows(table)[:50]:
            assert set(row) == names, table


def test_innocent_columns_do_not_announce_themselves():
    planted = json.loads((ROOT / "evals/ground_truth/planted.json").read_text())
    innocent = [p["column"] for p in planted["pii"] if p["planted_in_innocent_column"]]
    assert "crm.support_tickets.ref_2" in innocent and "crm.support_tickets.notes_free_text" in innocent
    for col in innocent:
        leaf = col.split(".")[-1]
        assert not re.search(r"msisdn|phone|email|iban|birth|address|name", leaf), leaf


def test_quality_defects_are_planted():
    planted = json.loads((ROOT / "evals/ground_truth/planted.json").read_text())
    kinds = {(d["table"], d["kind"]) for d in planted["quality_defects"]}
    assert ("finance.billing", "uniqueness") in kinds and ("network.usage_events", "completeness") in kinds
