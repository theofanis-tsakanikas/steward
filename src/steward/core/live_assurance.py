"""Claims 1 and 5, live side: judge what Sensitive Data Protection and Dataplex answered.

The capture (adapters/capture.py) asks and writes the answers down; this module takes them and says where they
break a claim. It never talks to GCP, so CI re-judges the committed evidence with no account.

DLP (claim 1). Two inspections are recorded: the **untagged columns of the live tables** (read as the custodian) and a
**control sample** of the generator's own rows, every column, through the same template.

  LIVE_DLP_UNTAGGED       personal data found in a column the contracts leave without a policy tag. Doctrine 7: nobody
                          declares such a column non-sensitive; the data has to go or the contract has to tag it.
  LIVE_DLP_TRUNCATED      an inspection answer was cut short, so "no finding" would be a statement about a prefix
  LIVE_DLP_TABLE_MISSING  a table of the estate was not inspected, and nothing says why
  LIVE_DLP_CONTROL_BLIND  the control sample did not come back with a kind no detector can miss (email, IBAN): an
                          empty answer on the live tables would then prove nothing
  LIVE_DLP_PARTIAL        (warn) a sample covered part of a table; the coverage is in the evidence

Dataplex (claim 5). Every scan must have run to completion, and its failed-row count per rule must equal the number of
rows the offline quality engine quarantined for that rule. Two engines that disagree on a rule are a finding, not a merge.

  LIVE_DQ_NOT_RUN         a scan ended in a state other than SUCCEEDED
  LIVE_DQ_COUNT           failed rows for a rule differ from the offline engine's
  LIVE_DQ_RULE_MISSING    a rule the offline engine quarantined for, that the compiled scans carry, is in no comparable scan
  LIVE_DQ_NOT_SCANNED     (info) a rule the compiled scans leave out on purpose (referential, policy-tagged column)
  LIVE_DQ_PARTIAL         (warn) a scan read a sample of the table, so its counts cannot be compared
"""

from __future__ import annotations

import re

from .compile_assurance import DLP_MAP
from .findings import Finding

INFOTYPE_KIND = {name: kind for kind, (name, _rx) in DLP_MAP.items()}
# kinds a template that works cannot miss on 200 synthetic rows: if these are not found the control is blind
UNMISSABLE = ("email", "iban")


def _walk(data: dict):
    """(label, table_record) for the live tables and the control tables."""
    for t in data.get("tables", []):
        yield "tables", t
    for t in data.get("control", {}).get("tables", []):
        yield "control", t


def verify_dlp(data: dict, tags: dict[str, str | None], tables: set[str]) -> list[Finding]:
    """`tags`: 'dataset.table.column' -> policy tag or None, from the contracts; `tables`: every table of the estate."""
    out: list[Finding] = []
    for label, t in _walk(data):
        if t.get("truncated"):
            out.append(
                Finding(
                    "LIVE_DLP_TRUNCATED",
                    "dlp",
                    f"{t['table']} ({label})",
                    "an answer was truncated and could not be split further: no finding is not evidence here",
                )
            )
        sample = t.get("sample")
        if sample and not sample.get("complete"):
            out.append(
                Finding(
                    "LIVE_DLP_PARTIAL",
                    "dlp",
                    t["table"],
                    f"sample of {sample['rows_limit']} of {sample['num_rows']} rows ({sample['coverage']:.0%})",
                    severity="warn",
                )
            )
    covered = {t["table"] for t in data.get("tables", [])}
    for table in sorted(tables - covered):
        out.append(Finding("LIVE_DLP_TABLE_MISSING", "dlp", table, "no inspection of this table was captured"))
    for label, rows in (("tables", data.get("findings", [])), ("control", data.get("control", {}).get("findings", []))):
        for r in rows:
            col = f"{r['table']}.{r['column']}"
            if col in tags and tags[col] is None:
                out.append(
                    Finding(
                        "LIVE_DLP_UNTAGGED",
                        "dlp",
                        col,
                        f"{r['info_type']} found in {r['rows_with_a_finding']} row(s) ({label}), "
                        "and the contracts declare no policy tag here",
                    )
                )
    if "control" in data:
        found = {r["kind"] for r in data["control"].get("findings", [])}
        for kind in UNMISSABLE:
            if kind not in found:
                out.append(
                    Finding(
                        "LIVE_DLP_CONTROL_BLIND",
                        "dlp",
                        kind,
                        "the control sample holds this kind and the template did not report it",
                    )
                )
    else:
        out.append(Finding("LIVE_DLP_CONTROL_BLIND", "dlp", "control", "the capture has no control sample"))
    return out


def verify_history(data: dict, tables: set[str]) -> list[Finding]:
    """Claim 3, live: BigQuery's own job history agrees with the catalogued estate.

      LIVE_HISTORY_ERROR          the history could not be read
      LIVE_HISTORY_NOT_LOADED     a catalogued table that no job in the window wrote
      LIVE_HISTORY_UNKNOWN_TABLE  a job wrote or read a table no contract or harvest knows
    The dashboard edges stay the offline cross-check's business: no Looker instance exists to run dashboard queries."""
    if data.get("outcome") == "error":
        return [Finding("LIVE_HISTORY_ERROR", "history", "job history", str(data.get("error", ""))[:200])]
    out: list[Finding] = []
    written = {j["destination"] for j in data["jobs"] if j["job_type"] == "LOAD" or j["statement_type"] != "SELECT"}
    for t in sorted(tables - written):
        out.append(
            Finding("LIVE_HISTORY_NOT_LOADED", "history", t, f"no job in the last {data['window_days']} days wrote it")
        )
    seen = {j["destination"] for j in data["jobs"]} | {r for j in data["jobs"] for r in j["referenced_tables"]}
    for t in sorted(seen - tables):
        out.append(
            Finding(
                "LIVE_HISTORY_UNKNOWN_TABLE", "history", t, "written or read by a job, and not in the catalogued estate"
            )
        )
    return out


def scan_table(scan_id: str, tables: list[str]) -> str | None:
    """`steward-dq-crm-customers` -> `crm.customers` (the id is the compiler's own slug of dataset and table)."""
    for t in tables:
        if scan_id == "steward-dq-" + re.sub(r"[^a-z0-9]+", "-", t.replace(".", "-").lower()):
            return t
    return None


def verify_dataplex(
    data: dict,
    source_counts: dict[str, int],
    quarantined_by_rule: dict[str, int],
    compiled_rules: set[str] | None = None,
) -> list[Finding]:
    """`source_counts`: table -> rows in the source (counted before the rules ran); `quarantined_by_rule`: rule id -> rows
    the offline engine quarantined for it (from `evals/quality`'s own result); `compiled_rules`: the rule names the
    compiled scans carry (a rule left out on purpose - a referential check, a policy-tagged column - is not Dataplex's
    to answer, and is reported as not scanned; None = every rule is expected to be scanned)."""
    out: list[Finding] = []
    expected = {k.lower(): v for k, v in quarantined_by_rule.items()}
    compared: set[str] = set()
    for s in data.get("scans", []):
        sid = s["scan"]
        if s.get("state") != "SUCCEEDED":
            out.append(
                Finding(
                    "LIVE_DQ_NOT_RUN", "dataplex", sid, f"state {s.get('state')}: {s.get('message') or 'no message'}"
                )
            )
            continue
        table = scan_table(sid, sorted(source_counts))
        if table is None or s.get("rows_scanned") != source_counts[table]:
            out.append(
                Finding(
                    "LIVE_DQ_PARTIAL",
                    "dataplex",
                    sid,
                    f"read {s.get('rows_scanned')} rows of {source_counts.get(table)}: not comparable",
                    severity="warn",
                )
            )
            continue
        for r in s["rules"]:
            rid = r["rule"]
            compared.add(rid)
            want = expected.get(rid, 0)
            if r["failed_rows"] != want:
                out.append(
                    Finding(
                        "LIVE_DQ_COUNT",
                        "dataplex",
                        f"{sid}:{rid}",
                        f"Dataplex failed {r['failed_rows']} row(s), the offline engine quarantined {want}",
                    )
                )
    for rid in sorted(set(expected) - compared):
        if not expected[rid]:
            continue
        if compiled_rules is not None and rid not in compiled_rules:
            out.append(
                Finding(
                    "LIVE_DQ_NOT_SCANNED",
                    "dataplex",
                    rid,
                    f"the offline engine quarantined {expected[rid]} row(s); the compiled scans leave this rule out "
                    "(see the scan description), so Dataplex says nothing about it",
                    severity="info",
                )
            )
            continue
        out.append(
            Finding(
                "LIVE_DQ_RULE_MISSING",
                "dataplex",
                rid,
                f"the offline engine quarantined {expected[rid]} row(s) for this rule; no comparable scan carries it",
            )
        )
    return out
