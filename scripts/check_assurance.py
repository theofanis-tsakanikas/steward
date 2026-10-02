#!/usr/bin/env python3
"""The live-assurance Terraform (DLP template, Dataplex scans) compiled from the contracts, read back and judged
against the contracts and the compiled access controls - not against the generator's own intentions.

  ASSURANCE_TAGGED_RULE  a Dataplex rule reads a policy-tagged column (the scan identity holds no Fine-Grained
                         Reader: the rule could only fail with an access error, or force a grant nobody made)
  ASSURANCE_IDENTITY     a scan does not run as its dataset's custodian seat (an identity outside the row access
                         policies reads zero rows, and zero rows pass completeness and uniqueness)
  ASSURANCE_ROWS         a scanned table's row access policies leave its custodian out of every unfiltered policy
  ASSURANCE_KIND         the DLP template does not ask for a kind the value detector can find
  ASSURANCE_QUOTE        the DLP template repeats the value it found (include_quote)
  ASSURANCE_NO_MINTER    a scan runs as a custodian seat, and Dataplex's service agent is not allowed to mint tokens for
                         that seat (the scan is refused at creation: first apply, 2026-10-02) - or is allowed more than
                         that one role, or on more than the one account
  ASSURANCE_UNBOUNDED    a scan of a table a thousand times larger would read more than the ceiling below (or a scan
                         has no valid sampling_percent): a limit that only holds for today's tiny tables is no limit
"""

from __future__ import annotations

import sys

from steward import io, pipeline
from steward.core.compile_assurance import compile_assurance
from steward.core.contract import DETECTABLE_KINDS

# Written out here on purpose: the generator's own table (DLP_MAP) is the thing under test.
EXPECTED_INFOTYPE = {
    "msisdn": "PHONE_NUMBER",
    "imsi": "STEWARD_IMSI",
    "imei": "IMEI_HARDWARE_ID",
    "email": "EMAIL_ADDRESS",
    "iban": "IBAN_CODE",
    "birth_date": "DATE_OF_BIRTH",
    "address": "STREET_ADDRESS",
}
# Written out here on purpose, like EXPECTED_INFOTYPE: the ceiling a scan of any table may never exceed.
CEILING_ROWS = 10_000
CEILING_BYTES = 32 * 1024 * 1024
ASSURANCE = "infra/assurance/generated.tf.json"
GOVERNANCE = "infra/governance/generated.tf.json"
# Written out here on purpose, like the ceilings: the member the generator names is the thing under test.
AGENT = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-dataplex.iam.gserviceaccount.com"


def problems() -> list[str]:
    e = pipeline.load()
    doc, gov = e.compiled[ASSURANCE], e.compiled[GOVERNANCE]
    out: list[str] = []
    scans = doc["resource"]["google_dataplex_datascan"]
    policies = gov["resource"].get("google_bigquery_row_access_policy", {}).values()
    for c in e.contracts:
        for tname, tbl in c.tables.items():
            scan = scans.get(f"dq_{c.dataset}_{tname}")
            if scan is None:
                continue
            at = f"{ASSURANCE} {c.dataset}.{tname}"
            tagged = {p for p, col in tbl.columns.items() if col.classification.tagged}
            for rule in scan["data_quality_spec"]["rules"]:
                if rule["column"] in tagged:
                    out.append(f"ERROR ASSURANCE_TAGGED_RULE {at} — rule {rule['name']} reads tagged {rule['column']}")
            want = f'${{trimprefix(var.principals["{c.custodian}"], "serviceAccount:")}}'
            got = scan.get("execution_identity", {}).get("service_account", {}).get("email")
            if got != want:
                out.append(f"ERROR ASSURANCE_IDENTITY {at} — runs as {got!r}, not the custodian {c.custodian}")
            minted = [
                m
                for m in doc["resource"].get("google_service_account_iam_member", {}).values()
                if m["service_account_id"].endswith(f'var.principals["{c.custodian}"], "serviceAccount:")}}')
            ]
            if [m["role"] for m in minted] != ["roles/iam.serviceAccountShortTermTokenMinter"] or any(
                m["member"] != AGENT for m in minted
            ):
                out.append(
                    f"ERROR ASSURANCE_NO_MINTER {at} — the Dataplex service agent must hold exactly the token minter "
                    f"role on {c.custodian}'s account, got {[(m['role'], m['member']) for m in minted]}"
                )
            mine = [n for n in policies if n["dataset_id"] == c.dataset and n["table_id"] == tname]
            ref = f'${{var.principals["{c.custodian}"]}}'
            if mine and not any(n["filter_predicate"] == "TRUE" and ref in n["grantees"] for n in mine):
                out.append(f"ERROR ASSURANCE_ROWS {at} — the custodian is in no unfiltered row access policy")
    out += _unbounded(e)
    cfg = doc["resource"]["google_data_loss_prevention_inspect_template"]["steward"]["inspect_config"]
    asked = {t["name"] for t in cfg.get("info_types", [])} | {
        t["info_type"]["name"] for t in cfg.get("custom_info_types", [])
    }
    for kind in DETECTABLE_KINDS:
        if EXPECTED_INFOTYPE.get(kind) not in asked:
            out.append(f"ERROR ASSURANCE_KIND {ASSURANCE} — the template does not ask for {kind}")
    if cfg.get("include_quote") is not False:
        out.append(f"ERROR ASSURANCE_QUOTE {ASSURANCE} — include_quote must be false")
    return out


def _unbounded(e) -> list[str]:
    """Compile the same contracts against tables 1000x larger and read each scan's percentage back."""
    out: list[str] = []
    sizes = io.table_sizes()
    for factor in (1, 1000):
        big = {t: (rows * factor, nbytes * factor) for t, (rows, nbytes) in sizes.items()}
        built = compile_assurance(
            e.contracts, e.compiled["infra/estate/generated.tf.json"], e.compiled[GOVERNANCE], big
        )[ASSURANCE]
        for key, scan in built["resource"]["google_dataplex_datascan"].items():
            ds, tbl = scan["labels"]["dataset"], key.removeprefix(f"dq_{scan['labels']['dataset']}_")
            rows, nbytes = big[f"{ds}.{tbl}"]
            pct = scan["data_quality_spec"].get("sampling_percent")
            if not isinstance(pct, int | float) or not 0 < pct <= 100:
                out.append(
                    f"ERROR ASSURANCE_UNBOUNDED {ASSURANCE} {ds}.{tbl} — sampling_percent {pct!r} is not in (0, 100]"
                )
            elif rows * pct / 100 > CEILING_ROWS or nbytes * pct / 100 > CEILING_BYTES:
                out.append(
                    f"ERROR ASSURANCE_UNBOUNDED {ASSURANCE} {ds}.{tbl} — at {rows} rows a scan reads "
                    f"{rows * pct / 100:.0f} rows, over the ceiling of {CEILING_ROWS} rows / {CEILING_BYTES} bytes"
                )
    return out


def main() -> int:
    found = problems()
    print("\n".join(found))
    if found:
        print(f"FAIL assurance: {len(found)} blocking finding(s)")
        return 1
    print("ok assurance: scans read untagged columns, as their custodian, over rows it sees; DLP asks for every kind")
    return 0


if __name__ == "__main__":
    sys.exit(main())
