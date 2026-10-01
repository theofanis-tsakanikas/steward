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
"""

from __future__ import annotations

import sys

from steward import pipeline
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
ASSURANCE = "infra/assurance/generated.tf.json"
GOVERNANCE = "infra/governance/generated.tf.json"


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
            mine = [n for n in policies if n["dataset_id"] == c.dataset and n["table_id"] == tname]
            ref = f'${{var.principals["{c.custodian}"]}}'
            if mine and not any(n["filter_predicate"] == "TRUE" and ref in n["grantees"] for n in mine):
                out.append(f"ERROR ASSURANCE_ROWS {at} — the custodian is in no unfiltered row access policy")
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
