#!/usr/bin/env python3
"""gate-proof — break each gate on purpose and require the NAMED gate to refuse, for the right reason.

Three rules make this a proof rather than a ritual:
  1. Green first.       Every gate runs on an unmutated copy and must pass before any mutation counts.
  2. A non-zero exit is not evidence.  The gate must exit non-zero AND print a blocking finding line
                        that carries the expected code and target. A crash, an import error or a
                        different finding is reported as WRONG REASON, and the run is red.
  3. STALE is not passed.  A mutation whose target text is no longer in the file did nothing; it is
                        reported STALE and the run is red.

Each mutation runs in its own throwaway copy of the repository (the working tree is never touched),
executing the copy's own code (PYTHONPATH=<copy>/src).

    python scripts/gate_proof.py            # run all
    python scripts/gate_proof.py --list     # name them
    python scripts/gate_proof.py --json out.json   # also write the results (the demo's Gates page reads it)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
GATES: dict[str, list[str]] = {
    "contracts": [PY, "-m", "steward.cli", "validate", "--today", "2026-10-01"],
    "contract-versions": [PY, "scripts/check_contract_versions.py", "--base", "HEAD"],
    "classification": [PY, "-m", "steward.cli", "scan"],
    "access": [PY, "-m", "steward.cli", "compile"],
    "access-eval": [PY, "evals/run.py", "access"],
    "generated": [PY, "scripts/generate.py", "--check"],
    "core-purity": [PY, "scripts/check_core_purity.py"],
    "contract-fields": [PY, "scripts/check_contract_fields.py"],
    "quality": [PY, "-m", "steward.cli", "quality"],
    "marketplace": [PY, "-m", "steward.cli", "marketplace"],
    "marketplace-eval": [PY, "evals/run.py", "marketplace"],
    "retention": [PY, "-m", "steward.cli", "retention"],
    "retention-eval": [PY, "evals/run.py", "retention"],
    "classification-eval": [PY, "evals/run.py", "classification"],
    "quality-eval": [PY, "evals/run.py", "quality"],
    "synthetic-check": [PY, "synthetic/generate.py", "--check"],
}


# Commands `make check` / `make evals` / CI run that are deliberately NOT proven here, and why.
EXCLUDED = {
    "pytest": "the unit tests are themselves assertions; a mutation would test pytest",
    "ruff": "style, not a governance gate",
    "scripts/tf_validate.py": "Terraform's own validator; generated Terraform is covered by the `generated` gate",
    "steward": "never matched: every steward subcommand must be a gate (listed so the rule is explicit)",
}
EXCLUDED.pop("steward")  # see above — present only as documentation of the rule
# CI also runs `uv sync` (installation) and gitleaks inline (an external scanner with its own test suite);
# neither is a make target, so neither is in scope here.


@dataclass
class Mutation:
    name: str
    gate: str
    file: str
    find: str
    replace: str
    marker: tuple[str, str]  # (code, target) that must appear on one blocking finding line
    why: str
    claim: str
    count: int = 1  # the find text must occur EXACTLY this many times, else STALE


MUTATIONS: list[Mutation] = [
    Mutation(
        "retention deleted",
        "contracts",
        "contracts/finance.yaml",
        'retention:\n  period_days: 3650\n  legal_basis: "Tax and accounting record-keeping obligation, 10 years (illustrative; varies by country)"\n',
        "",
        ("RETENTION_MISSING", "finance:retention"),
        "a dataset with no retention period fails the build (doctrine 3)",
        "7",
    ),
    Mutation(
        "owner deleted",
        "contracts",
        "contracts/crm.yaml",
        "owner: group:crm-owners@halverra.example\n",
        "",
        ("OWNERSHIP_MISSING", "crm:owner"),
        "a dataset with no owner fails the build (doctrine 3)",
        "4",
    ),
    Mutation(
        "new column, no contract entry",
        "contracts",
        "synthetic/data/_schema.json",
        '"name": "iban",\n        "type": "STRING"\n      },',
        '"name": "iban",\n        "type": "STRING"\n      },\n      {"mode": "NULLABLE", "name": "payer_phone", "type": "STRING"},',
        ("COLUMN_UNDECLARED", "finance.billing.payer_phone"),
        "a column the estate has and the contract does not is drift",
        "1",
    ),
    Mutation(
        "waiver for personal data",
        "contracts",
        "contracts/_waivers.yaml",
        "waivers:\n",
        "waivers:\n  - {id: W-999, finding: PII_UNTAGGED, target: crm.support_tickets.ref_2, reason: legacy usage will be fixed later,\n"
        "     requested_by: 'user:katerina.vasileiou@halverra.example', approved_by: 'user:dimitris.nikolaou@halverra.example',\n"
        "     approved_on: 2026-10-01, expires: 2026-10-30}\n",
        ("WAIVER_REFUSED", "W-999"),
        "no waiver can open personal data (doctrine 7)",
        "1",
    ),
    Mutation(
        "contract edited without a version bump",
        "contract-versions",
        "contracts/crm.yaml",
        "description: Customer master data",
        "description: Customer master data (edited)",
        ("VERSION_NOT_BUMPED", "crm"),
        "a changed contract must be a new version (doctrine 4)",
        "4",
    ),
    Mutation(
        "the tag removed from ref_2",
        "classification",
        "contracts/crm.yaml",
        """      ref_2:
        {type: STRING, classification: personal, kinds: [msisdn],
         description: "Meant as an internal reference; in practice agents store the callback number here.",
         masking: {analyst: hash, fraud_investigator: clear, steward: last_four, bi_service: hash}}""",
        """      ref_2:
        {type: STRING, classification: internal,
         description: "Meant as an internal reference; in practice agents store the callback number here."}""",
        ("PII_UNTAGGED", "crm.support_tickets.ref_2"),
        "phone numbers found by value in a column the contract calls internal",
        "1",
    ),
    Mutation(
        "compiler forgets the safe state",
        "classification",
        "src/steward/core/compile.py",
        '                if info.type != "RECORD":\n                    tag_of[path] = RESTRICTED',
        '                if info.type != "RECORD":\n                    pass',
        ("PII_UNTAGGED", "legacy.legacy_crm_export.tel_a"),
        "an uncontracted table's PII must compile to `restricted`",
        "1",
    ),
    Mutation(
        "analyst sees MSISDN in clear",
        "access",
        "contracts/crm.yaml",
        "masking: {analyst: hash, fraud_investigator: clear, steward: last_four, bi_service: hash},\n         quality: [{id: Q-CRM-003",
        "masking: {analyst: clear, fraud_investigator: clear, steward: last_four, bi_service: hash},\n         quality: [{id: Q-CRM-003",
        ("ROLE_CEILING_EXCEEDED", "crm.customers.msisdn"),
        "a role ceiling the contract cannot raise",
        "2",
    ),
    Mutation(
        "year mask on a STRING",
        "access",
        "contracts/crm.yaml",
        "masking: {analyst: email_mask, fraud_investigator: nullify, steward: email_mask, bi_service: hash}",
        "masking: {analyst: year_only, fraud_investigator: nullify, steward: email_mask, bi_service: hash}",
        ("MASKING_TYPE_INVALID", "crm.customers.email"),
        "a masking rule BigQuery would reject on that type",
        "2",
    ),
    Mutation(
        "compiler grants clear to every masked seat",
        "access-eval",
        "src/steward/core/compile.py",
        '                value = "clear" if rule == Masking.CLEAR else PREDEFINED[rule]',
        '                value = "clear"',
        ("MISMATCH tag-grants", "analyst@DE: expected EMAIL_MASK compiled clear"),
        "compiled controls must be exactly what the contracts imply",
        "2",
    ),
    Mutation(
        "pipeline SA handed Fine-Grained Reader",
        "access-eval",
        "src/steward/core/compile.py",
        "                    grants[key][seat] = value\n",
        '                    grants[key][seat] = value\n                    grants[key][c.custodian] = "clear"\n',
        ("MISMATCH tag-grants", "group:data-platform@halverra.example: expected None compiled clear"),
        "the custodian writes data and reads no tagged column in clear (doctrine 5)",
        "2",
    ),
    Mutation(
        "project-level Fine-Grained Reader",
        "access-eval",
        "src/steward/core/compile.py",
        '            "role": "roles/bigquery.jobUser",',
        '            "role": "roles/datacatalog.categoryFineGrainedReader",',
        ("UNMODELLED_ACCESS", "google_project_iam_member"),
        "access the simulator cannot evaluate is refused, never ignored",
        "2",
    ),
    Mutation(
        "last-four compiled as a hash",
        "access-eval",
        "src/steward/core/compile.py",
        '    Masking.LAST_FOUR: "LAST_FOUR_CHARACTERS",',
        '    Masking.LAST_FOUR: "SHA256",',
        ("MISMATCH tag-grants", "expected LAST_FOUR_CHARACTERS compiled SHA256"),
        "the eval reads the contract vocabulary with its own map, not the compiler's",
        "2",
    ),
    Mutation(
        "an inline access block on a dataset",
        "access-eval",
        "src/steward/core/compile.py",
        '            "max_time_travel_hours": TIME_TRAVEL_HOURS,\n',
        '            "max_time_travel_hours": TIME_TRAVEL_HOURS,\n            "access": [{"role": "READER", "special_group": "allAuthenticatedUsers"}],\n',
        ("UNMODELLED_ACCESS", "google_bigquery_dataset"),
        "a grant hidden inside a non-IAM resource is still a grant",
        "2",
    ),
    Mutation(
        "a Fine-Grained Reader in the estate layer",
        "access-eval",
        "src/steward/core/compile.py",
        '    R["google_bigquery_dataset"] = datasets\n',
        '    R["google_bigquery_dataset"] = datasets\n    R["google_data_catalog_policy_tag_iam_member"] = {"x": {"policy_tag": "t", "role": "roles/datacatalog.categoryFineGrainedReader", "member": "group:all@halverra.example"}}\n',
        ("UNMODELLED_ACCESS", "estate"),
        "IAM in a layer the model does not read is refused, not ignored",
        "2",
    ),
    Mutation(
        "a loader that drops a quarantined row",
        "quality",
        "src/steward/quality_run.py",
        "for q in res.quarantined)",
        "for q in res.quarantined[1:])",
        ("QUALITY_ROWS_LOST", "finance.billing"),
        "source = loaded + quarantined, counted from what was written (claim 5)",
        "5",
    ),
    Mutation(
        "quarantine without its rule id",
        "quality",
        "src/steward/core/quality.py",
        'sorted({f["rule_id"] for f in failures})',
        "[]",
        ("QUARANTINE_UNATTRIBUTED", "finance.billing"),
        "a quarantined row carries the rule that sent it there",
        "5",
    ),
    Mutation(
        "the self-approval check deleted",
        "marketplace-eval",
        "src/steward/core/marketplace.py",
        "        if approver == requester:\n",
        "        if False:\n",
        ("MISMATCH", "R-004:"),
        "R-004's approver owns network and sits in analyst@IT — only the self-approval check stops it (doctrine 5)",
        "6",
    ),
    Mutation(
        "a service account's approval accepted",
        "marketplace-eval",
        "src/steward/core/marketplace.py",
        '        if approver.startswith("serviceaccount:"):\n',
        "        if False:\n",
        ("MISMATCH", "R-005:"),
        "no pipeline approves access (doctrine 5); the refusal still holds as APPROVER_NOT_HUMAN — this proves the eval checks the reason",
        "6",
    ),
    Mutation(
        "a grant handed to the whole seat",
        "marketplace-eval",
        "src/steward/core/marketplace.py",
        '        return self.request["requester"]\n',
        '        return self.request["seat"]\n',
        ("MISMATCH", "R-001:"),
        "the grant goes to the person who asked, never to their whole seat",
        "6",
    ),
    Mutation(
        "a grant compiled without its expiry",
        "marketplace",
        "src/steward/core/compile_marketplace.py",
        '            "condition": {',
        '            "_no_condition": {',
        ("GRANT_WITHOUT_EXPIRY", "network:user:eleni.kosta@halverra.example"),
        "every grant carries an IAM Condition expiry",
        "6",
    ),
    Mutation(
        "the evaluator reads the clock",
        "core-purity",
        "src/steward/core/marketplace.py",
        '    now = ts(snapshot["captured_at"])\n',
        "    from time import time\n\n    now = datetime.fromtimestamp(time())\n",
        ("CORE_CLOCK", "src/steward/core/marketplace.py"),
        "now comes from the evidence capture time, never from a clock the code controls (claim 6 trap)",
        "6",
    ),
    Mutation(
        "partition expiry from the dataset, not the table",
        "retention",
        "src/steward/core/compile.py",
        '                tp["expiration_ms"] = c.table_retention_days(tname) * DAY_MS',
        '                tp["expiration_ms"] = c.retention.period_days * DAY_MS',
        ("RETENTION_MISMATCH", "network.network_events"),
        "the compiled expiry is exactly the declared period, table override included (claim 7)",
        "7",
    ),
    Mutation(
        "a row-retention DELETE never compiled",
        "retention",
        "src/steward/core/retention.py",
        '            if row["mechanism"]["kind"] != "scheduled_delete":\n                continue',
        '            if row["mechanism"]["kind"] != "scheduled_delete" or row["table"] == "support_tickets":\n                continue',
        ("RETENTION_NOT_COMPILED", "crm.support_tickets"),
        "a declared row retention with no DELETE behind it is a promise nobody keeps",
        "7",
    ),
    Mutation(
        "the erasure caveat dropped from the report",
        "retention-eval",
        "src/steward/core/retention.py",
        '    return {"caveat": CAVEAT, "rows": rows}',
        '    return {"caveat": "", "rows": rows}',
        ("CAVEAT_MISSING", "first line"),
        "the report's first line says deletion is not immediate (time travel + fail-safe)",
        "7",
    ),
    Mutation(
        "a contract field nothing reads, named like one that is read elsewhere",
        "contract-fields",
        "src/steward/core/contract.py",
        "    log_sink: LogSink | None = None\n",
        "    log_sink: LogSink | None = None\n    mode: str | None = None\n",
        ("FIELD_UNREAD", "Contract.mode"),
        "a field in a contract that no generator reads is a defect (CLAUDE.md, the contract layer)",
        "all",
    ),
    Mutation(
        "a detector that reads column names",
        "classification-eval",
        "src/steward/core/classify.py",
        "    return [detect_column(c, vals, scan_date) for c, vals in sorted(columns.items())]\n",
        "    return [ColumnDetection(c, len(vals), {}, name_heuristics(c)) for c, vals in sorted(columns.items())]\n",
        ("FAIL claim 1", "recall < 1.0"),
        "claim 1's trap: detection by name misses ref_2, notes_free_text and the legacy columns",
        "1",
    ),
    Mutation(
        "duplicates loaded instead of quarantined",
        "quality-eval",
        "src/steward/core/quality.py",
        "            if v in bucket:\n",
        "            if False:\n",
        ("MISSED", "finance.billing"),
        "the two planted duplicate invoices must be quarantined by Q-FIN-002, not loaded",
        "5",
    ),
    Mutation(
        "a synthetic row edited by hand",
        "synthetic-check",
        "synthetic/data/finance.billing.jsonl",
        '"invoice_id":"INV-2026-000001"',
        '"invoice_id":"INV-2026-999999"',
        ("SYNTHETIC_STALE", "finance.billing"),
        "the synthetic estate is generated, seeded and byte-identical; a hand edit is drift",
        "1",
    ),
    Mutation(
        "a waiver left to lapse",
        "contracts",
        "contracts/_waivers.yaml",
        "    approved_on: 2026-10-01\n    expires: 2026-11-30\n",
        "    approved_on: 2026-08-01\n    expires: 2026-09-15\n",
        ("CONTRACT_MISSING", "legacy.legacy_crm_export"),
        "exceptions expire; on expiry the finding returns and CI goes red (doctrine 6)",
        "4",
    ),
    Mutation(
        "the type-drift check dropped",
        "contract-fields",
        "src/steward/core/validate.py",
        '            elif col.type != info.type:\n                f.append(\n                    Finding(\n                        "TYPE_MISMATCH", GATE, f"{table}.{path}", f"contract says {col.type}, estate has {info.type}"\n                    )\n                )\n',
        "",
        ("READER_STALE", "Column.type"),
        "a field whose only reader is removed is a promise nobody keeps",
        "all",
    ),
    Mutation(
        "generated Terraform edited by hand",
        "generated",
        "infra/estate/generated.tf.json",
        '"description": "No contract. Every column is tagged `restricted` and denied to every role (doctrine 1).",',
        '"description": "No contract.",',
        ("GENERATED_STALE", "infra/estate/generated.tf.json"),
        "every control is generated; a hand edit is drift",
        "2",
        count=1,
    ),
    Mutation(
        "a cloud SDK in the core",
        "core-purity",
        "src/steward/core/compile.py",
        "import hashlib\n",
        "import hashlib\nfrom google.cloud import bigquery  # noqa\n",
        ("CORE_IMPURE", "src/steward/core/compile.py"),
        "the core is pure; claims are provable offline",
        "all",
    ),
]

_IGNORE = shutil.ignore_patterns(
    ".venv", ".terraform", "__pycache__", ".pytest_cache", ".ruff_cache", "out", "node_modules"
)


def _copy(src: Path, dst: Path) -> Path:
    shutil.copytree(src, dst, ignore=_IGNORE, symlinks=True)
    return dst


def _snapshot(dst: Path, worktree: bool) -> Path:
    """The pristine tree every mutation is cloned from: git HEAD by default — what is committed is what is
    proven — or the working tree with --worktree, for local iteration."""
    if worktree:
        return _copy(REPO, dst)
    dst.mkdir(parents=True)
    archive = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=REPO, capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(dst)], input=archive.stdout, check=True)
    shutil.copytree(REPO / ".git", dst / ".git")  # the contract-versions gate compares with HEAD
    return dst


def _run(root: Path, gate: str) -> tuple[int | None, str]:
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "STEWARD_BASE_REF": ""}
    try:
        r = subprocess.run(GATES[gate], cwd=root, env=env, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT after 600 s"
    return r.returncode, r.stdout + r.stderr


def _finding_line(output: str, code: str, target: str) -> str | None:
    """The line that proves the RIGHT check refused: it STARTS with the code (after an optional
    severity), is not a warning, info, success or waived line, and names the target."""
    for line in output.splitlines():
        s = line.strip()
        if s.startswith(("WARN", "INFO", "ok ")) or "[waived by" in s:
            continue
        body = s[len("ERROR") :].strip() if s.startswith("ERROR") else s
        if body.startswith(code) and target in body:
            return s
    return None


def _argv(cmd: str) -> tuple[str, ...]:
    """Normalise a command to compare argv token-exactly: `uv run python X a` → (X, a); `uv run steward v`
    and `python -m steward.cli v` → (steward, v)."""
    import shlex

    t = shlex.split(cmd)
    while t and (
        Path(t[0]).name in ("uv", "python", "python3")
        or t[0] in ("run", PY, "-q")
        or Path(t[0]).name.startswith("python3.")
    ):
        t = t[1:]
    if t[:2] == ["-m", "steward.cli"]:
        t = ["steward", *t[2:]]
    if t[:1] == ["-m"]:
        t = t[1:]
    return tuple(t)


def _commands(target: str) -> list[str]:
    """What `make <target>` would run — prerequisites and variables expanded — split into single commands."""
    import re as _re

    r = subprocess.run(["make", "-n", target], cwd=REPO, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"UNGATED cannot expand `make {target}`: {r.stderr.strip()}")
    return [c.strip() for line in r.stdout.splitlines() for c in _re.split(r"&&|;|\|", line) if c.strip()]


def _ci_make_targets() -> list[str]:
    import yaml as _yaml

    wf = _yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text())
    targets = []
    for job in wf["jobs"].values():
        for step in job.get("steps", []):
            for line in str(step.get("run", "")).splitlines():
                if line.strip().startswith("make "):
                    targets += line.split()[1:]
    return targets


def _uncovered_make_commands() -> list[str]:
    """Every command that `make check`, `make evals` and the CI workflow's `make` steps run must be a gate
    here (argv-exact: the gate's argv starts with the command's) or EXCLUDED by its executable."""
    gates = [_argv(" ".join(v)) for v in GATES.values()]
    missing = []
    targets = sorted(set(["check", *_ci_make_targets()]) - {"gate-proof", "evals", "claims"})
    for cmd in [c for t in targets for c in _commands(t)]:
        argv = _argv(cmd)
        if not argv or argv[0] in EXCLUDED or Path(argv[0]).name in EXCLUDED:
            continue
        if not any(g[: len(argv)] == argv for g in gates):
            missing.append(cmd)
    for harness in sorted(p.parent.name for p in (REPO / "evals").glob("*/eval.py")):
        if ("evals/run.py", harness) not in gates:
            missing.append(f"evals/run.py {harness}")
    return sorted(set(missing))


def run_all(selected: list[Mutation], worktree: bool = False) -> tuple[list[dict], bool]:
    results, ok = [], True
    with tempfile.TemporaryDirectory(prefix="gate-proof-") as tmp:
        pristine = _snapshot(Path(tmp) / "pristine", worktree)  # one snapshot; every copy is cloned from it
        baseline_out: dict[str, str] = {}
        for gate in sorted({m.gate for m in selected}):
            code, out = _run(pristine, gate)
            if code != 0:
                print(f"BASELINE RED  {gate}: the unmutated tree already fails — nothing below would prove anything")
                print(out[-1500:])
                return [], False
            baseline_out[gate] = out
        for i, m in enumerate(selected, 1):
            root = _copy(pristine, Path(tmp) / f"m{i}")
            path = root / m.file
            text = path.read_text()
            found = text.count(m.find)
            if found != m.count:
                status = "STALE"
                detail = f"target text found {found}× in {m.file}, expected exactly {m.count}× — " + (
                    "the mutation would change nothing"
                    if not found
                    else "an ambiguous target can silently hit the wrong line"
                )
            elif _finding_line(baseline_out[m.gate], *m.marker):
                status, detail = "WRONG REASON", "the marker already appears in the unmutated gate's output"
            else:
                path.write_text(text.replace(m.find, m.replace, m.count))
                code, out = _run(root, m.gate)
                line = _finding_line(out, *m.marker)
                tail = (out.strip().splitlines() or ["(no output)"])[-1][:160]
                if code is None:
                    status, detail = "WRONG REASON", "the gate timed out"
                elif code == 0:
                    status, detail = "LET THROUGH", "the gate exited 0"
                elif "Traceback (most recent call last)" in out:
                    status, detail = "WRONG REASON", "the gate crashed instead of refusing: " + tail
                elif line is None:
                    status, detail = "WRONG REASON", "non-zero exit, but not the expected finding: " + tail
                else:
                    status, detail = "REFUSED", line[:300]
            shutil.rmtree(root, ignore_errors=True)
            ok &= status == "REFUSED"
            mark = "\033[32m" if status == "REFUSED" else "\033[31m"
            print(
                f"{i:2}. {mark}{status:12}\033[0m [{m.gate}] {m.name}\n      expect {m.marker[0]} … {m.marker[1]}\n      {detail}"
            )
            results.append(
                {
                    "n": i,
                    "name": m.name,
                    "gate": m.gate,
                    "claim": m.claim,
                    "file": m.file,
                    "why": m.why,
                    "expect": list(m.marker),
                    "status": status,
                    "detail": detail,
                }
            )
    return results, ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--only", help="run only mutations whose gate matches")
    ap.add_argument(
        "--worktree", action="store_true", help="prove the working tree instead of git HEAD (local iteration)"
    )
    args = ap.parse_args(argv)
    selected = [m for m in MUTATIONS if not args.only or m.gate == args.only]
    if args.list:
        for m in selected:
            print(f"[{m.gate}] {m.name} → {m.marker[0]}")
        return 0
    covered = {m.gate for m in MUTATIONS}
    missing = sorted(set(GATES) - covered)
    uncovered = _uncovered_make_commands()
    results, ok = run_all(selected, args.worktree)
    if missing:
        print(f"UNPROVEN gates (no mutation): {missing}")
        ok = False
    if uncovered and not args.only:
        print(f"UNGATED commands (in make check / evals, neither a gate here nor EXCLUDED): {uncovered}")
        ok = False
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "rules": ["green first", "a non-zero exit is not evidence", "STALE is not passed"],
                    "results": results,
                    "ok": ok,
                },
                indent=2,
            )
            + "\n"
        )
    n_ref = sum(r["status"] == "REFUSED" for r in results)
    print(f"{'ok' if ok else 'FAIL'} gate-proof: {n_ref}/{len(results)} mutations refused by their named gate")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
