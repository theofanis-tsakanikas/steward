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
    "workflows": [PY, "scripts/check_workflows.py"],
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
    "lineage": [PY, "-m", "steward.cli", "lineage"],
    "lineage-eval": [PY, "evals/run.py", "lineage"],
    "catalog": [PY, "-m", "steward.cli", "catalog"],
    "catalog-eval": [PY, "evals/run.py", "catalog"],
    "evidence": [PY, "-m", "steward.cli", "evidence-check"],
    "demo-figures": [PY, "scripts/check_demo_numbers.py"],
    "oidc-subjects": [PY, "scripts/check_oidc_subjects.py"],
    "deployer-grants": [PY, "scripts/check_deployer_grants.py"],
    "assurance": [PY, "scripts/check_assurance.py"],
    "live": [PY, "scripts/check_live.py"],
    "dlp-eval": [PY, "evals/run.py", "dlp"],
    "dataplex-eval": [PY, "evals/run.py", "dataplex"],
    "ids": [PY, "scripts/check_ids.py"],
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


# Built at import so this file does not contain the contiguous canary the ids gate searches for.
_IDS_CANARY = "x-planted-" + "project-number-000"

MUTATIONS: list[Mutation] = [
    Mutation(
        "a live project number written into the tree",
        "ids",
        "CHANGELOG.md",
        "# Changelog\n",
        f"# Changelog\n\n{_IDS_CANARY}\n",
        ("ID_IN_TREE", "CHANGELOG.md"),
        "a planted identifier in a tracked file that is not the scanner is a leak; env/tfvars supply live ids",
        "1",
    ),
    Mutation(
        "personal data found live in a column the contract leaves untagged",
        "live",
        "evidence/live/dlp.json",
        '  "findings": [],\n  "method"',
        '  "findings": [{"column": "segment", "findings": 3, "info_type": "PERSON_NAME", "kind": "name", "likelihoods": {"LIKELY": 3}, "rows_with_a_finding": 3, "table": "crm.customers"}],\n  "method"',
        ("LIVE_DLP_UNTAGGED", "crm.customers.segment"),
        "a captured finding in an untagged column is the failure claim 1 exists for, and the capture is judged again offline",
        "1",
    ),
    Mutation(
        "personal data found live in a column the contract leaves untagged",
        "dlp-eval",
        "evidence/live/dlp.json",
        '  "findings": [],\n  "method"',
        '  "findings": [{"column": "segment", "findings": 3, "info_type": "PERSON_NAME", "kind": "name", "likelihoods": {"LIKELY": 3}, "rows_with_a_finding": 3, "table": "crm.customers"}],\n  "method"',
        ("LIVE_DLP_UNTAGGED", "crm.customers.segment"),
        "the harness judges the same capture with the same core function and says why with its n",
        "1",
    ),
    Mutation(
        "a Dataplex count that disagrees with the offline engine",
        "live",
        "evidence/live/dataplex.json",
        '"failed_rows": 2,\n      "null_rows": null,\n      "passed": false,\n      "passed_rows": 1800,\n      "rule": "q-fin-002"',
        '"failed_rows": 0,\n      "null_rows": null,\n      "passed": true,\n      "passed_rows": 1802,\n      "rule": "q-fin-002"',
        ("LIVE_DQ_COUNT", "q-fin-002"),
        "two independent engines must fail the same rows; a scan that finds fewer is a rule that does not do what it says",
        "5",
    ),
    Mutation(
        "a Dataplex count that disagrees with the offline engine",
        "dataplex-eval",
        "evidence/live/dataplex.json",
        '"failed_rows": 2,\n      "null_rows": null,\n      "passed": false,\n      "passed_rows": 1800,\n      "rule": "q-fin-002"',
        '"failed_rows": 0,\n      "null_rows": null,\n      "passed": true,\n      "passed_rows": 1802,\n      "rule": "q-fin-002"',
        ("LIVE_DQ_COUNT", "q-fin-002"),
        "the harness prints each rule beside its offline count; a disagreement is blocking",
        "5",
    ),
    Mutation(
        "an analyst transcript that shows a clear e-mail address",
        "live",
        "evidence/live/access.json",
        '"email": "XXXXX@example.net",\n      "msisdn": "U707guKL68qSDXL982nZuy0sZsu4TamrNS/+ZkDDSTc="',
        '"email": "CLEAR",\n      "msisdn": "U707guKL68qSDXL982nZuy0sZsu4TamrNS/+ZkDDSTc="',
        ("LIVE_VALUE_NOT_MASKED", "customers"),
        "the role transcript is the proof that BigQuery masked; a clear value in it is the claim failing",
        "2",
    ),
    Mutation(
        "an approved grant whose expiry has already passed, still present in the estate",
        "live",
        "evidence/live/iam.json",
        '"expression": "request.time < timestamp(\\"2026-10-06T16:00:00Z\\")",\n     "title": "steward-R-002"',
        '"expression": "request.time < timestamp(\\"2026-09-30T16:00:00Z\\")",\n     "title": "steward-R-002"',
        ("GRANT_EXPIRED_PRESENT", "crm:user:paolo.marino@halverra.example"),
        "an expired grant still present in the estate turns CI red, judged at the capture's own timestamp",
        "6",
    ),
    Mutation(
        "an analyst transcript that includes another country's row",
        "live",
        "evidence/live/access.json",
        '"country": "GR",\n      "created_at": "2017-10-10T01:10:45Z",\n      "customer_id": "E6SyP6pt/TvuQnJwEHWaJmttWNjSxH6lEkCe0WaFVm0=",\n      "email": "XXXXX@example.net",\n      "msisdn": "U707guKL68qSDXL982nZuy0sZsu4TamrNS/+ZkDDSTc="',
        '"country": "IT",\n      "created_at": "2017-10-10T01:10:45Z",\n      "customer_id": "E6SyP6pt/TvuQnJwEHWaJmttWNjSxH6lEkCe0WaFVm0=",\n      "email": "XXXXX@example.net",\n      "msisdn": "U707guKL68qSDXL982nZuy0sZsu4TamrNS/+ZkDDSTc="',
        ("LIVE_ROW_POLICY", "customers"),
        "the row access policy is compiled Terraform; a GR analyst seeing an IT row is the claim failing",
        "2",
    ),
    Mutation(
        "a hashed identifier replaced with a different row's hash",
        "live",
        "evidence/live/access.json",
        '"email": "XXXXX@example.net",\n      "msisdn": "U707guKL68qSDXL982nZuy0sZsu4TamrNS/+ZkDDSTc="',
        '"email": "XXXXX@example.net",\n      "msisdn": "pg9iBijnKlcybKMorcVv2EQFHQ0rkdt5tXT7GoQ4NSM="',
        ("LIVE_VALUE_NOT_MASKED", "customers"),
        "SHA256 is judged against the true value, not 'looks like a hash'",
        "2",
    ),
    Mutation(
        "the access-review sink answered no events",
        "live",
        "evidence/live/audit.json",
        '"outcome": "rows",\n  "rows": [',
        '"outcome": "rows",\n  "rows": []  , "dropped": [',
        ("LIVE_AUDIT_EMPTY", "access review"),
        "an empty audit trail is not evidence that the sink saw the grant being used",
        "6",
    ),
    Mutation(
        "an unexplained principal holds dataViewer",
        "live",
        "evidence/live/iam.json",
        '"member": "specialGroup:projectReaders"',
        '"member": "user:attacker@evil.example"',
        ("LIVE_IAM_UNKNOWN_MEMBER", "attacker@evil.example"),
        "a principal that is not a seat, a requester, or a documented default is a grant nobody approved",
        "6",
        6,
    ),
    Mutation(
        "capture runs as the destroyer",
        "workflows",
        ".github/workflows/capture.yml",
        "vars.GCP_DEPLOYER_SERVICE_ACCOUNT",
        "vars.GCP_DESTROYER_SERVICE_ACCOUNT",
        ("WORKFLOW_IDENTITY", ".github/workflows/capture.yml"),
        "a capture holds the deployer's reach (seat impersonation) and not the destroyer's",
        "2",
    ),
    Mutation(
        "a capture workflow that also applies",
        "workflows",
        ".github/workflows/capture.yml",
        '          uv run steward capture --project "$PROJECT" --what "${captures[@]}" --out out/live\n',
        '          uv run steward capture --project "$PROJECT" --what "${captures[@]}" --out out/live\n          terraform apply -auto-approve\n',
        ("WORKFLOW_CAPTURE_APPLIES", ".github/workflows/capture.yml"),
        "a capture reads the estate and nothing else may ride on its identity",
        "2",
    ),
    Mutation(
        "deploy also runs on every push",
        "workflows",
        ".github/workflows/deploy.yml",
        "on:\n  workflow_dispatch:\n    inputs:\n      expires_at:",
        "on:\n  push:\n    branches: [main]\n  workflow_dispatch:\n    inputs:\n      expires_at:",
        ("WORKFLOW_TRIGGER", ".github/workflows/deploy.yml"),
        "an apply is dispatched by a person, never by a push",
        "6",
    ),
    Mutation(
        "the apply job outside the deploy environment",
        "workflows",
        ".github/workflows/deploy.yml",
        "    environment: deploy\n",
        "",
        ("WORKFLOW_NO_ENVIRONMENT", ".github/workflows/deploy.yml"),
        "the federation trust names the environment: without it no credentials are issued",
        "6",
    ),
    Mutation(
        "a destroy that can be cancelled half way",
        "workflows",
        ".github/workflows/destroy.yml",
        "cancel-in-progress: false",
        "cancel-in-progress: true",
        ("WORKFLOW_CANCELS_APPLY", ".github/workflows/destroy.yml"),
        "a cancelled destroy leaves a lock and a half-removed estate",
        "7",
    ),
    Mutation(
        "a layer destroyed under another state prefix than it was applied with",
        "workflows",
        ".github/workflows/destroy.yml",
        'prefix=assurance"',
        'prefix=assurance-old"',
        ("WORKFLOW_LAYER_MISSING", ".github/workflows/destroy.yml"),
        "a layer left out of destroy outlives the estate and keeps costing",
        "7",
    ),
    Mutation(
        "destroy runs as the identity the budget guard switches off",
        "workflows",
        ".github/workflows/destroy.yml",
        "vars.GCP_DESTROYER_SERVICE_ACCOUNT",
        "vars.GCP_DEPLOYER_SERVICE_ACCOUNT",
        ("WORKFLOW_IDENTITY", ".github/workflows/destroy.yml"),
        "a spend stop must never close the way to take the estate down",
        "7",
    ),
    Mutation(
        "an input expanded inside a script run as the deployer",
        "workflows",
        ".github/workflows/deploy.yml",
        '-var "publish_version=$PUBLISH_VERSION"',
        '-var "publish_version=${{ inputs.publish_version }}"',
        ("WORKFLOW_INJECTION", ".github/workflows/deploy.yml"),
        "a typed input is code the moment it is expanded into a script that holds the deployer identity",
        "7",
        count=1,
    ),
    Mutation(
        "a destroy step that no longer destroys",
        "workflows",
        ".github/workflows/destroy.yml",
        '          terraform destroy -input=false -auto-approve -var "project_id=$PROJECT" -var "expires_at=2000-01-01"\n',
        "          echo skipped\n",
        ("WORKFLOW_LAYER_STEP", ".github/workflows/destroy.yml"),
        "a prefix with no destroy behind it leaves the layer standing and the run green",
        "7",
        count=2,
    ),
    Mutation(
        "a destroy that runs without the typed confirmation",
        "workflows",
        ".github/workflows/destroy.yml",
        "    if: ${{ inputs.confirm == 'destroy-steward' }}\n",
        "",
        ("WORKFLOW_NO_CONFIRM", ".github/workflows/destroy.yml"),
        "destroy is the one irreversible button",
        "7",
        count=1,
    ),
    Mutation(
        "a destroy step that is skipped when an earlier one fails",
        "workflows",
        ".github/workflows/destroy.yml",
        "      - name: estate\n        if: ${{ always() }}\n",
        "      - name: estate\n",
        ("WORKFLOW_STRANDS", ".github/workflows/destroy.yml"),
        "one failed layer must not strand the datasets behind it",
        "7",
        count=1,
    ),
    Mutation(
        "the provider read from a secret",
        "workflows",
        ".github/workflows/deploy.yml",
        "workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}",
        "workload_identity_provider: ${{ secrets.WIF_PROVIDER }}",
        ("WORKFLOW_KEY", ".github/workflows/deploy.yml"),
        "no secret exists in this project: federation only",
        "7",
        count=1,
    ),
    Mutation(
        "id-token granted to every job",
        "workflows",
        ".github/workflows/deploy.yml",
        "permissions:\n  contents: read\n\n# Never cancel",
        "permissions:\n  contents: read\n  id-token: write\n\n# Never cancel",
        ("WORKFLOW_NO_ENVIRONMENT", ".github/workflows/deploy.yml"),
        "a token minted outside the environment is a token the trust never meant to issue",
        "7",
        count=1,
    ),
    Mutation(
        "a key in the deploy workflow",
        "workflows",
        ".github/workflows/deploy.yml",
        "          service_account: ${{ vars.GCP_DEPLOYER_SERVICE_ACCOUNT }}\n      - uses: google-github-actions/setup-gcloud@v2\n\n      - name: estate",
        "          service_account: ${{ vars.GCP_DEPLOYER_SERVICE_ACCOUNT }}\n          credentials_json: ${{ secrets.GCP_KEY }}\n      - uses: google-github-actions/setup-gcloud@v2\n\n      - name: estate",
        ("WORKFLOW_KEY", ".github/workflows/deploy.yml"),
        "no long-lived credential exists anywhere (CLAUDE.md)",
        "6",
    ),
    Mutation(
        "offline CI handed a cloud identity",
        "workflows",
        ".github/workflows/ci.yml",
        "permissions:\n  contents: read\n\nconcurrency:",
        "permissions:\n  contents: read\n  id-token: write\n\nconcurrency:",
        ("CI_HAS_CREDENTIALS", ".github/workflows/ci.yml"),
        "every claim is provable with no GCP account: CI holds no credentials",
        "6",
    ),
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
        "a ceiling raised in the same PR, unapproved",
        "contract-versions",
        "contracts/_roles.yaml",
        "  bi_service: {clear_kinds: []}\n",
        "  bi_service: {clear_kinds: [msisdn]}\n",
        ("CEILING_RAISED", "_roles.yaml:ceilings.bi_service"),
        "raising a ceiling is an approval by someone else, not an edit (doctrines 5 and 7)",
        "7",
    ),
    Mutation(
        "a dashboard field renamed in LookML only",
        "lineage",
        "lookml/dashboards/billing_health.dashboard.lookml",
        "fields: [billing.status, billing.total_amount]",
        "fields: [billing.status, billing.total_amt]",
        ("UNRESOLVED_FIELD", "billing_health/amount_by_status/billing.total_amt"),
        "every dashboard field resolves to a catalogued column (claim 3)",
        "3",
    ),
    Mutation(
        "the job-history cross-check merged instead of compared",
        "lineage-eval",
        "src/steward/core/lineage.py",
        "        if a != b:\n",
        "        if False:\n",
        ("NOT_DETECTED", "LINEAGE_DISAGREEMENT billing_health"),
        "a disagreement between LookML and the job history is a finding, never a merge (claim 3 trap)",
        "3",
    ),
    Mutation(
        "the sensitive-on-dashboard check removed",
        "lineage-eval",
        "src/steward/core/lineage.py",
        '                        elif seen == "clear" and leaf in access.tagged:\n',
        "                        elif False:\n",
        ("NOT_DETECTED", "SENSITIVE_UNMASKED_ON_DASHBOARD"),
        "a tagged column reaches a dashboard only masked for the connection's role (claim 3)",
        "3",
    ),
    Mutation(
        "dashboards judged as the wrong role",
        "lineage",
        "src/steward/core/lineage.py",
        "            access = access_for(role)\n",
        '            access = access_for("fraud_investigator")\n',
        ("DASHBOARD_FIELD_DENIED", "customer_overview/customers_by_country/customers.country"),
        "a field is judged by what its model's connection role reads, not any role's",
        "3",
    ),
    Mutation(
        "a load job that no longer lands the billing table",
        "lineage",
        "evals/lineage/query_history.json",
        '"destination": "finance.billing",',
        '"destination": "finance.billing_old",',
        ("LINEAGE_UNTRACED", "billing_health:finance.billing"),
        "every table a dashboard reads traces back to a landing source (claim 3)",
        "3",
    ),
    Mutation(
        "a dataset's domain generated without its owners",
        "catalog",
        "src/steward/core/catalog.py",
        '            dcmd["responsibilities"] = _responsibilities(by_ds[ds], group_ids)',
        "            pass",
        ("CATALOG_OWNER_MISSING", "crm:Owner"),
        "the catalog names an owner, steward and custodian for every contracted dataset — read back, not assumed (claim 4)",
        "4",
    ),
    Mutation(
        "a weaker classification written to the catalog",
        "catalog",
        "src/steward/core/catalog.py",
        '"Personal Data Classification": col.classification.value,',
        '"Personal Data Classification": "public",',
        ("CLASSIFICATION_MISMATCH", "crm.customers.msisdn"),
        "the catalog never says less than the contract (claim 4; doctrine 1)",
        "4",
    ),
    Mutation(
        "a diff that resends everything",
        "catalog",
        "src/steward/core/catalog.py",
        "            if _comparable(_owned(stored, send)) == _comparable(send):\n                continue",
        "            if False:\n                continue",
        ("SYNC_NOT_IDEMPOTENT", "second-sync"),
        "a second sync of an unchanged estate sends 0 commands (claim 4)",
        "4",
    ),
    Mutation(
        "a timestamp counted as content",
        "catalog",
        "src/steward/core/catalog.py",
        'VOLATILE = frozenset({"Last Changed"})',
        "VOLATILE = frozenset()",
        ("RECONCILE_DIFFERS", "Business Glossary / Active Customer"),
        "`Last Changed` is when content changed, not content: the reconciliation must not report it as drift (claim 4)",
        "4",
    ),
    Mutation(
        "the catalog's mode left unsaid",
        "catalog",
        "src/steward/core/catalog.py",
        'f"(catalog mode: {mode}). Edits made here are reverted by the next sync."',
        '"Edits made here are reverted by the next sync."',
        ("MODE_UNSTATED", "community"),
        "the catalog says whether it was generated for MOCK or REAL (doctrine 2)",
        "4",
    ),
    Mutation(
        "a relation written in the shorthand",
        "catalog",
        "src/steward/core/catalog.py",
        'IS_PART_OF_TABLE = "Column:is part of:contains:Table:TARGET"',
        'IS_PART_OF_TABLE = "is part of:TARGET"',
        ("CATALOG_REJECTED", "UNKNOWN_RELATION"),
        "the validating mock refuses a relation key the Import API guide does not document (claim 4)",
        "4",
    ),
    Mutation(
        "a mock that accepts any asset type",
        "catalog-eval",
        "src/steward/adapters/collibra/mock.py",
        'spec = self.model["asset_types"].get(typ)\n',
        'spec = self.model["asset_types"].get(typ) or self.model["asset_types"]["Table"]\n',
        ("NOT_DETECTED", "UNKNOWN_ASSET_TYPE"),
        "a mock that accepts anything proves nothing (claim 4 trap)",
        "4",
    ),
    Mutation(
        "a mock that lets dangling relations through",
        "catalog-eval",
        "src/steward/adapters/collibra/mock.py",
        '            if found is None:\n                raise Rejection("DANGLING_RELATION"',
        '            if found is None:\n                continue\n                raise Rejection("DANGLING_RELATION"',
        ("NOT_DETECTED", "DANGLING_RELATION"),
        "a relation to an asset that does not exist is refused (claim 4)",
        "4",
    ),
    Mutation(
        "a mock that writes before it validates",
        "catalog-eval",
        "src/steward/adapters/collibra/mock.py",
        "        staged = copy.deepcopy(self.state)\n",
        "        staged = self.state\n",
        ("MISMATCH", "and the catalog changed"),
        "a refused job commits nothing — one transaction (continueOnError=false)",
        "4",
    ),
    Mutation(
        "reconciliation blind to hand edits",
        "catalog-eval",
        "src/steward/core/catalog.py",
        "        if changed:\n            differing.append(",
        "        if False:\n            differing.append(",
        ("NOT_DETECTED", "RECONCILE_DIFFERS"),
        "an owner or description changed by hand in the catalog is drift the reconciliation reports (claim 4)",
        "4",
    ),
    Mutation(
        "the previous description not kept",
        "catalog-eval",
        "src/steward/adapters/collibra/mock.py",
        'if a != "Last Changed" and before not in (None, after):',
        "if False:",
        ("MISMATCH", "the previous description is kept"),
        "a correction never erases what was previously stated (doctrine 4)",
        "4",
    ),
    Mutation(
        "a failed sync that is never stale",
        "catalog-eval",
        "src/steward/catalog_sync.py",
        '    if report.get("status") == "ok":\n        return None',
        "    return None",
        ("MISMATCH", "stale marker names the last good sync"),
        "when the catalog cannot be updated it says so, with the age of the last good sync (doctrine 1)",
        "4",
    ),
    Mutation(
        "an owner nobody declared, invented",
        "catalog-eval",
        "src/steward/core/catalog.py",
        '        if group not in group_ids:\n            raise UnknownOwnerGroup(f"{c.dataset}: {role} {group!r} has no user group id in the catalog directory")\n        out[role] = [{"userGroup": {"id": group_ids[group]}}]',
        '        out[role] = [{"userGroup": {"id": group_ids.get(group, "00000000-0000-0000-0000-000000000000")}}]',
        ("NOT_DETECTED", "OWNER_GROUP_UNKNOWN"),
        "no default owner (doctrine 3)",
        "4",
    ),
    Mutation(
        "a retention period misstated in the catalog",
        "catalog",
        "src/steward/core/catalog.py",
        '"Retention Period": f"{c.retention.period_days} days",',
        '"Retention Period": f"{c.retention.period_days * 10} days",',
        ("CATALOG_RETENTION_MISMATCH", "crm"),
        "the catalog states the retention the contract declares — read back (claim 4, claim 7)",
        "4",
    ),
    Mutation(
        "masking dropped from the catalog",
        "catalog",
        "src/steward/core/catalog.py",
        '"Masking": json.dumps({r: m.value for r, m in sorted(col.masking.items())})\n                        if col.masking\n                        else "none (untagged)",',
        '"Masking": "none (untagged)",',
        ("CATALOG_MASKING_MISMATCH", "crm.customers.msisdn"),
        "the catalog states the masking each role gets, as the contract declares it (claim 4)",
        "4",
    ),
    Mutation(
        "an undeclared column catalogued as public",
        "catalog",
        "src/steward/core/catalog.py",
        '"Personal Data Classification": "restricted (no contract)",',
        '"Personal Data Classification": "public",',
        ("CATALOG_UNDECLARED_NOT_RESTRICTED", "halverra-data.legacy"),
        "a column no contract declares is held at restricted — never `public` (doctrine 1, 3)",
        "4",
    ),
    Mutation(
        "a drafted glossary term born Accepted",
        "catalog",
        "src/steward/core/catalog.py",
        '"Under Review"\n                if conflict\n                else "Candidate",  # a drafted definition is accepted by a steward, not by the sync',
        '"Accepted",',
        ("CATALOG_SELF_ACCEPTED", "Active Customer"),
        "nothing accepts its own drafted description (doctrine 5)",
        "4",
    ),
    Mutation(
        "reconciliation blind to relations",
        "catalog-eval",
        "src/steward/core/catalog.py",
        "for fld in sorted(set(a) | set(b)):",
        'for fld in sorted((set(a) | set(b)) - {"relations"}):',
        ("MISMATCH", "relation and foreign attribute listed as differing"),
        "a relation removed by hand is drift the reconciliation reports (claim 4)",
        "4",
    ),
    Mutation(
        "reconciliation blind to status",
        "catalog-eval",
        "src/steward/core/catalog.py",
        "for fld in sorted(set(a) | set(b)):",
        'for fld in sorted((set(a) | set(b)) - {"status"}):',
        ("MISMATCH", "relation and foreign attribute listed as differing"),
        "a status changed by hand on a contracted asset is drift (claim 4)",
        "4",
    ),
    Mutation(
        "reconciliation blind to stale generated assets",
        "catalog-eval",
        "src/steward/core/catalog.py",
        'if k_ not in wanted and not (k_[0] == "Asset" and v["type"]["name"] in physical)',
        'if False and k_ not in wanted and not (k_[0] == "Asset" and v["type"]["name"] in physical)',
        ("NOT_DETECTED", "RECONCILE_STALE_GENERATED"),
        "a retired dashboard must not go on advertising its columns (claim 4)",
        "4",
    ),
    Mutation(
        "diff counting what Steward does not write",
        "catalog-eval",
        "src/steward/core/catalog.py",
        "if _comparable(_owned(stored, send)) == _comparable(send):",
        "if _comparable(stored) == _comparable(send):",
        ("MISMATCH", "then sends nothing"),
        "a second sync sends 0 even when the catalog holds something an import cannot remove (claim 4)",
        "4",
    ),
    Mutation(
        "a steward's acceptance overwritten",
        "catalog-eval",
        "src/steward/core/catalog.py",
        'HUMAN_OWNED = {("Asset", "Business Term"): ("status",)}',
        "HUMAN_OWNED = {}",
        ("MISMATCH", "a steward's acceptance survives the next sync"),
        "the pipeline proposes, a steward accepts, the sync never undoes it (doctrine 5)",
        "4",
    ),
    Mutation(
        "an unscanned column reported clean",
        "catalog-eval",
        "src/steward/core/catalog.py",
        'if scanned is None or f"{fq}.{path}" in scanned',
        "if True",
        ("MISMATCH", "a column the scan never saw says so"),
        "an absence of findings is not a finding of absence (doctrine 1)",
        "4",
    ),
    Mutation(
        "the log-sink exception that never expires",
        "catalog-eval",
        "src/steward/catalog_sync.py",
        "live = at[:10] <= until",
        "live = True",
        ("MISMATCH", "and after it the dataset is drift again"),
        "an exception expires and the finding returns (doctrine 6)",
        "4",
    ),
    Mutation(
        "a stale marker kept out of the catalog",
        "catalog-eval",
        "src/steward/catalog_sync.py",
        'report["marker_written"] = _write_marker(client, report["stale"], at)',
        'report["marker_written"] = False',
        ("MISMATCH", "the catalog itself shows the stale marker"),
        "the catalog shows a stale marker with its age (doctrine 1)",
        "4",
    ),
    Mutation(
        "a mock with no anchor check",
        "catalog-eval",
        "src/steward/adapters/collibra/mock.py",
        "if typ != anchor_type:",
        "if False:",
        ("NOT_DETECTED", "a report anchoring"),
        "a relation is refused when its anchor is the wrong type, whatever its target (claim 4)",
        "4",
    ),
    Mutation(
        "a mock that skips required attributes",
        "catalog-eval",
        "src/steward/adapters/collibra/mock.py",
        "        if missing:\n",
        "        if False:\n",
        ("NOT_DETECTED", "a required attribute missing"),
        "a required attribute missing is refused (claim 4)",
        "4",
    ),
    Mutation(
        "a mock that skips the domain-type rule",
        "catalog-eval",
        "src/steward/adapters/collibra/mock.py",
        'if dtype != spec["domain_type"]:',
        "if False:",
        ("NOT_DETECTED", "a column placed in a glossary domain"),
        "an asset type belongs in its domain type (claim 4)",
        "4",
    ),
    Mutation(
        "a mock that trusts any user group id",
        "catalog-eval",
        "src/steward/adapters/collibra/mock.py",
        'if kind == "userGroup" and ref["id"] not in directory:',
        "if False:",
        ("NOT_DETECTED", "a user group id the directory does not have"),
        "an owner is a group the directory knows (doctrine 3)",
        "4",
    ),
    Mutation(
        "a mock with asset responsibilities on",
        "catalog-eval",
        "src/steward/adapters/collibra/mock.py",
        'if rt == "Asset" and not self.model.get("asset_responsibilities", False):',
        "if False:",
        ("NOT_DETECTED", "responsibilities on an asset"),
        "the default instance refuses asset-level responsibilities; so does the mock (claim 4)",
        "4",
    ),
    Mutation(
        "a mock that accepts a relation target twice",
        "catalog-eval",
        "src/steward/adapters/collibra/mock.py",
        "if tk in seen:",
        "if False:",
        ("NOT_DETECTED", "a relation target listed twice"),
        "a malformed relation list is refused (claim 4)",
        "4",
    ),
    Mutation(
        "a mock that accepts unknown identifier keys",
        "catalog-eval",
        "src/steward/adapters/collibra/mock.py",
        'and obj["name"] and set(obj) <= allowed):',
        'and obj["name"]):',
        ("NOT_DETECTED", "an extra key in an identifier"),
        "the mock refuses shapes the guide does not document (claim 4)",
        "4",
    ),
    Mutation(
        "evidence edited by hand",
        "evidence",
        "evidence/fixture/quality.json",
        '"source": 1802',
        '"source": 1795',
        ("EVIDENCE_DIGEST_MISMATCH", "fixture/quality.json"),
        "the demo shows only evidence whose digest still matches its payload",
        "5",
    ),
    Mutation(
        "the repository changed, the evidence did not",
        "evidence",
        "contracts/crm.yaml",
        "description: Customer master data",
        "description: Customer master data (reworded)",
        ("EVIDENCE_STALE", "fixture/estate.json"),
        "evidence is a function of the repository: a change that moves it must be re-recorded",
        "4",
    ),
    Mutation(
        "an evidence file the manifest does not vouch for",
        "evidence",
        "evidence/MANIFEST.json",
        '"fixture/retention.json": "',
        '"fixture/retention.json": "0',
        ("EVIDENCE_UNLISTED", "fixture/retention.json"),
        "every evidence file is listed in the manifest with its digest",
        "7",
    ),
    Mutation(
        "a gate-proof mutation renamed after the run was recorded",
        "evidence",
        "scripts/gate_proof.py",
        '        "owner deleted",\n        "contracts",',
        '        "owner removed",\n        "contracts",',
        ("GATES_STALE", "gates"),
        "the Gates page shows a recorded run: it must still list exactly today's mutations",
        "4",
    ),
    Mutation(
        "a figure typed into a page",
        "demo-figures",
        "app/pages/4_Quality.py",
        'a.metric("Failures planted in the sources", q["planted"])',
        'a.metric("Failures planted in the sources", 14)',
        ("DEMO_FIGURE_HARDCODED", "app/pages/4_Quality.py"),
        "every number the demo shows comes from an evidence file",
        "5",
    ),
    Mutation(
        "a date typed into a page",
        "demo-figures",
        "app/pages/7_Retention.py",
        'st.caption("A dataset with no retention period fails the build; there is no default period.")',
        'st.caption("Checked 2026-10-01: a dataset with no retention period fails the build.")',
        ("DEMO_FIGURE_HARDCODED", "app/pages/7_Retention.py"),
        "a date or a count in prose is a figure too",
        "7",
    ),
    Mutation(
        "the trust clauses joined by OR",
        "oidc-subjects",
        "infra/bootstrap/wif.tf",
        'trust_condition = join(" && ", [',
        'trust_condition = join(" || ", [',
        ("OIDC_JOINER", "infra/bootstrap/wif.tf"),
        "with OR any one clause is enough: any repository with a deploy environment gets in",
        "6",
    ),
    Mutation(
        "a trust that is written but not applied",
        "oidc-subjects",
        "infra/bootstrap/wif.tf",
        "attribute_condition = local.trust_condition",
        'attribute_condition = "true"',
        ("OIDC_UNWIRED", "infra/bootstrap/wif.tf"),
        "the clauses only protect if the provider applies them",
        "6",
    ),
    Mutation(
        "the repository id pinned to the wrong variable",
        "oidc-subjects",
        "infra/bootstrap/wif.tf",
        "\"assertion.repository_id == '${var.github_repository_id}'\"",
        "\"assertion.repository_id == '${var.github_owner_id}'\"",
        ("OIDC_CLAUSES", "infra/bootstrap/wif.tf"),
        "a clause that names the wrong value pins nothing, and a substring check would not notice",
        "6",
    ),
    Mutation(
        "a third environment in the trust",
        "oidc-subjects",
        "infra/bootstrap/wif.tf",
        'trusted_environments = ["deploy", "destroy"]',
        'trusted_environments = ["deploy", "destroy", "dev"]',
        ("OIDC_ENVS", "infra/bootstrap/wif.tf"),
        "an environment anyone can create is a door",
        "6",
    ),
    Mutation(
        "the repository matched by prefix",
        "oidc-subjects",
        "infra/bootstrap/wif.tf",
        "\"assertion.repository == '${var.github_owner}/${var.github_repo}'\"",
        "\"assertion.repository.startsWith('${var.github_owner}/')\"",
        ("OIDC_PATTERN", "infra/bootstrap/wif.tf"),
        "every value in the trust is an exact match, never a pattern",
        "6",
    ),
    Mutation(
        "the trust no longer pins the main branch",
        "oidc-subjects",
        "infra/bootstrap/wif.tf",
        "    \"assertion.ref == 'refs/heads/main'\",\n",
        "",
        ("OIDC_CLAUSES", "infra/bootstrap/wif.tf"),
        "a branch someone pushes to must not be able to apply",
        "6",
    ),
    Mutation(
        "the deployer open to a whole owner",
        "oidc-subjects",
        "infra/bootstrap/wif.tf",
        '/attribute.environment/deploy"',
        '/attribute.repository_owner_id/${var.github_owner_id}"',
        ("OIDC_FEDERATION_OPEN", "infra/bootstrap/wif.tf"),
        "only a job in the deploy environment may become the deployer, not everything the owner has",
        "6",
    ),
    Mutation(
        "a public principal granted on the state bucket",
        "oidc-subjects",
        "infra/bootstrap/deployer.tf",
        'resource "google_storage_bucket_iam_member" "ci_state" {',
        'resource "google_storage_bucket_iam_member" "open" {\n  bucket = google_storage_bucket.state.name\n  role   = "roles/storage.objectViewer"\n  member = "allAuthenticatedUsers"\n}\n\nresource "google_storage_bucket_iam_member" "ci_state" {',
        ("OIDC_PUBLIC", "infra/bootstrap/deployer.tf"),
        "state holds every resource id; nobody outside the project reads it",
        "6",
    ),
    Mutation(
        "a service-account key",
        "oidc-subjects",
        "infra/bootstrap/deployer.tf",
        'resource "google_storage_bucket_iam_member" "ci_state" {',
        'resource "google_service_account_key" "deployer" {\n  service_account_id = google_service_account.deployer.name\n}\n\nresource "google_storage_bucket_iam_member" "ci_state" {',
        ("KEY_FORBIDDEN", "infra/bootstrap/deployer.tf"),
        "no long-lived credential exists anywhere (CLAUDE.md)",
        "6",
    ),
    Mutation(
        "a quality rule on a policy-tagged column",
        "assurance",
        "src/steward/core/compile_assurance.py",
        "elif col.classification.tagged:",
        "elif False:",
        ("ASSURANCE_TAGGED_RULE", "infra/assurance/generated.tf.json"),
        "a scan identity with no Fine-Grained Reader can only fail there, or be given a grant nobody made",
        "5",
    ),
    Mutation(
        "a scan with no execution identity",
        "assurance",
        "src/steward/core/compile_assurance.py",
        '"execution_identity": {',
        '"execution_identity_unset": {',
        ("ASSURANCE_IDENTITY", "infra/assurance/generated.tf.json"),
        "a scan as any identity outside the row policies reads zero rows, and zero rows pass",
        "5",
    ),
    Mutation(
        "a scan whose service agent may not mint a token for its custodian",
        "assurance",
        "src/steward/core/compile_assurance.py",
        '"role": "roles/iam.serviceAccountShortTermTokenMinter",\n                "member": "serviceAccount:service-${data.google_project.this.number}@gcp-sa-dataplex',
        '"role": "roles/viewer",\n                "member": "serviceAccount:service-${data.google_project.this.number}@gcp-sa-dataplex',
        ("ASSURANCE_NO_MINTER", "infra/assurance/generated.tf.json"),
        "without the minter Dataplex refuses the scan at creation; with a broader role the agent could impersonate more",
        "5",
    ),
    Mutation(
        "a DLP finding that repeats the value",
        "assurance",
        "src/steward/core/compile_assurance.py",
        '"include_quote": False',
        '"include_quote": True',
        ("ASSURANCE_QUOTE", "infra/assurance/generated.tf.json"),
        "a finding names the column and the kind, never the value",
        "5",
    ),
    Mutation(
        "a masked column used as a clustering field",
        "contracts",
        "synthetic/data/_schema.json",
        '"network.usage_events": {\n    "cluster": [\n      "country",\n      "event_type"\n    ],',
        '"network.usage_events": {\n    "cluster": [\n      "msisdn",\n      "event_type"\n    ],',
        ("MASKED_COLUMN_CLUSTERED", "network.usage_events.msisdn"),
        "BigQuery refuses every masked read of such a table: the live capture of 2026-10-02 found it the hard way",
        "2",
    ),
    Mutation(
        "a scan that ignores the row ceiling",
        "assurance",
        "src/steward/core/sampling.py",
        "    pct = math.floor(s.coverage * 1000) / 10\n",
        "    pct = 100.0\n",
        ("ASSURANCE_UNBOUNDED", "infra/assurance/generated.tf.json"),
        "a limit that holds only for today's tiny tables is no limit: a table 1000x larger must still be sampled down",
        "1",
    ),
    Mutation(
        "a row ceiling raised a hundredfold",
        "assurance",
        "src/steward/core/sampling.py",
        "MAX_INSPECT_ROWS = 10_000\n",
        "MAX_INSPECT_ROWS = 1_000_000\n",
        ("ASSURANCE_UNBOUNDED", "infra/assurance/generated.tf.json"),
        "the ceiling is written down twice, in the code and in the gate, so that moving one is seen",
        "1",
    ),
    Mutation(
        "a layer grants a project role the deployer may not delegate",
        "deployer-grants",
        "infra/governance/generated.tf.json",
        '"role": "roles/bigquery.jobUser"',
        '"role": "roles/bigquery.dataViewer"',
        ("DEPLOYER_UNDELEGABLE", "infra/governance/generated.tf.json"),
        "the first apply would be refused on a denial, or the condition widened to hide it",
        "6",
        count=10,
    ),
    Mutation(
        "the deployer allowed to delegate a role nothing grants",
        "deployer-grants",
        "infra/bootstrap/deployer.tf",
        'delegable_roles = ["roles/bigquery.jobUser"]',
        'delegable_roles = ["roles/bigquery.jobUser", "roles/owner"]',
        ("DEPLOYER_DELEGATES_UNUSED", "infra/bootstrap/deployer.tf"),
        "a power nothing needs is a power someone else can use",
        "6",
    ),
    Mutation(
        "projectIamAdmin bound without its condition",
        "deployer-grants",
        "infra/bootstrap/deployer.tf",
        "for_each = contains(keys(local.role_conditions), each.value.role) ? [local.role_conditions[each.value.role]] : []",
        "for_each = []",
        ("DEPLOYER_CONDITION_MISSING", "infra/bootstrap/deployer.tf"),
        "unconditioned, the deployer can grant itself any role",
        "6",
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
    proven — or the working tree with --worktree, for local iteration. A detached `git worktree` works in
    a plain clone, inside another worktree and in CI's shallow checkout alike."""
    if worktree:
        return _copy(REPO, dst)
    subprocess.run(["git", "worktree", "add", "--detach", "--quiet", str(dst), "HEAD"], cwd=REPO, check=True)
    return dst


def _drop_snapshot(dst: Path) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", str(dst)], cwd=REPO, capture_output=True)


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

    r = subprocess.run(["make", "-n", "--no-print-directory", target], cwd=REPO, capture_output=True, text=True)
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
    with tempfile.TemporaryDirectory(prefix="gate-proof-") as tmp:
        pristine = _snapshot(Path(tmp) / "pristine", worktree)  # one snapshot; every copy is cloned from it
        try:
            return _run_all(selected, pristine)
        finally:
            if not worktree:
                _drop_snapshot(pristine)


def _run_all(selected: list[Mutation], pristine: Path) -> tuple[list[dict], bool]:
    results, ok = [], True
    tmp = pristine.parent
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
        "--skip",
        help="run every mutation except those of these gates (comma-separated). Used to record the run the Gates"
        " page shows: the evidence gate checks that record, so it cannot be part of it (CI runs it every time)",
    )
    ap.add_argument(
        "--worktree", action="store_true", help="prove the working tree instead of git HEAD (local iteration)"
    )
    args = ap.parse_args(argv)
    skip = set(filter(None, (args.skip or "").split(",")))
    selected = [m for m in MUTATIONS if (not args.only or m.gate == args.only) and m.gate not in skip]
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
    if uncovered and not args.only and not skip:
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
