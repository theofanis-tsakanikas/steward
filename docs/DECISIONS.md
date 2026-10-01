# DECISIONS

Schema: **Scope · Technology · Method · Deliberately deferred**. Every entry: what, why, what was rejected.

## Scope
- **S1 — A fictional operator, synthetic data only.** Why: public repo; no real personal data; no impersonation. Rejected: public datasets with real people; anything branded.
- **S2 — Governance of an analytics estate, not of the operational network.** Why: the role is BigQuery + Looker + Collibra. Rejected: OSS/BSS systems.
- **S3 — Seven claims, timeboxed to 4–5 days.** Why: interview ≈ 2026-10-07. Rejected: a broader platform that would not finish.

## Technology
- **T1 — BigQuery (EU multi-region or `europe-west1`, decided on day one).** Location is permanent per dataset; chosen once.
- **T2 — Terraform `google` / `google-beta`;** where a resource has no Terraform (verify per item in GCP-CONSTRAINTS), a scripted, idempotent apply inside the layer, with a CI check that fails the day a provider ships it.
- **T3 — Python 3.12, uv, pydantic for contracts, `lkml` for LookML, Streamlit for the demo.** Rejected: a JS front end (time), Looker Studio as the demo (cannot show governance internals).
- **T4 — Cloud Run jobs + Cloud Scheduler for automation, not Cloud Composer.** Why: Composer costs tens of euros per day standing. Rejected for now: Composer; see deferred D1.
- **T5 — Collibra behind an adapter with a validating mock.** Why: no self-serve Collibra; a trial is requested. Real mode is configuration. See `COLLIBRA.md`.
- **T6 — Workload Identity Federation from GitHub Actions; no SA keys.**

## Method
- **M1 — Contracts are the single source of truth;** every control and catalog asset is generated and `--check`ed.
- **M2 — Live runs capture evidence (JSON + digests) re-checked offline;** the demo reads evidence, so it survives `destroy`.
- **M3 — Every gate has a gate-proof mutation.**
- **M4 — Deploy → capture → destroy; spend recorded.**

## Resolved by the author (2026-10-01)
- **P1 — Repository visibility: PRIVATE now, public later.** Going public is a separate step after a
  pre-publish pass (`readme-standard`, gitleaks history scan, naming rule check, no project ids / billing ids in history).
- **P2 — BigQuery location: `EU` multi-region.** Policy-tag taxonomies and every dataset in `eu`.
- **P3 — Autonomous build.** The session builds, reviews and merges its own work without waiting for the
  author, up to the point where real GCP resources would be created (see `CLAUDE.md` → Git workflow).
  The author reviews the finished result.

## Deliberately deferred (each with an unlock condition or an expiry)
| Id | What | Unlock / expiry |
|---|---|---|
| D1 | OpenLineage from Airflow via a one-day Cloud Composer environment | unlock: phases 1–3 closed and ≥ €20 budget left |
| D2 | Real Collibra sync (T024) | **expiry 2026-10-05**: no trial by then → mock stands, stated everywhere |
| D3 | Looker API (usage-based report expiry from real System Activity) | unlock: a Looker trial exists; until then usage is a fixture, stated |
| D4 | Model-proposed descriptions (T031) | unlock: T030 closed before 2026-10-06 |
| D5 | Dataform for transformations | unlock: never for this timebox unless asked |
| D6 | VPC Service Controls perimeter | unlock: needs an organization node; if the project has none, documented only |

## Decided during the build (session, 2026-10-01)
- **B1 — The operator is "Halverra Telecom", domain `halverra.example`.** Searched 2026-10-01: no
  operator or well-known brand by that name; `.example` is reserved (RFC 2606) so no principal in the
  repository can ever resolve to a real mailbox. Rejected: "Corvane" (a registered UK company exists).
- **B2 — The naming rule in `CLAUDE.md` no longer names a real company, even as a negative example.**
  A public repository that names a company in order to say it is not about that company is about that
  company. The first commit was amended before any push, so no history carries the name.
- **B3 — The GitHub repository was created by the session (private), not by the author.** DAY-ONE step 6
  listed it as manual, but the autonomous build (P3) cannot open its first PR without it; `gh` was
  already authenticated as the author. The WIF half of step 6 stays with T010.
- **B4 — Contract fields read by a later atom, named here so none is orphaned.** `lawful_basis` →
  catalog attribute (T021) · `marketplace.listable`, `max_grant_days`, `grantable_roles`,
  `approvers` → marketplace flow (T006) · `retention.mode/column/rule` → compiled partition expiration
  and scheduled DELETE (T007) · `kinds` → role ceilings (T004) and the classification gate (T003) ·
  `masking` → policy tags and data policies (T004) · `quality`, `freshness` → rules engine (T005) ·
  `row_access` → row access policies (T004). T008 adds a check that every contract field is read by
  at least one generator or gate; until then this list is the record.
- **B5 — Only `CONTRACT_MISSING` is waivable (allowlist; `TABLE_UNDECLARED` removed by the verification pass, since deleting a declared table and waiving it would drop its tags), for at most 90 days,
  approved by a member of `group:privacy-office` who is neither the requester nor an owner of the
  waived dataset.** A waiver that could suppress a missing owner, retention or classification would be
  doctrine 3 with a deadline attached. Found by the T002 hostile review (finding 1).
- **B6 — Known limits of the contract checks, accepted.** `legal_basis`/`lawful_basis` only has to
  *name* an instrument (regex on Art./Directive/Regulation/law/obligation) — "Art. nothing" passes;
  whether the cited basis is right is a privacy-office review, not a regex. Directory groups may not
  nest (refused, not expanded). Contracts are `contracts/*.yaml` only; any other placement is an error.
- **B7 — Claim 1's gate checks the *compiled* tag, so T003 and T004 land as one PR.** The T003 review
  found that PII in the uncontracted legacy table passed as a warning while the only blocking finding
  (CONTRACT_MISSING) was waived — a waiver unlocking value-detected PII, doctrine 7 broken in practice.
  The fix: a detected column passes only if the compiled schema carries its policy tag. For a table no
  contract declares, the compiler tags every leaf `restricted` (no reader, no data policy); its PII is
  then reported `PII_HELD_AT_SAFE_STATE` (info) — and only while W-001 lives; on expiry CONTRACT_MISSING
  is red again. That makes the compiler part of claim 1's gate, so both atoms close together.
- **B8 — Data masking needs the project to belong to an organization.** Read 2026-10-01 in the BigQuery
  masking docs: "The project containing the policy tag taxonomy must belong to an organization."
  Policy tags themselves (deny vs Fine-Grained Reader) and row access policies carry no such statement.
  Consequence for claim 2 live (T012): with no organization, the three-role transcript can show
  deny / clear / row-filtered, but not masked values. Options in docs/DAY-ONE.md step 1b. The offline
  half of claim 2 is unaffected.
- **B9 — Every partitioned table requires a partition filter.** A deterministic rule, not a contract
  field: a query that would scan every partition is refused (cost control, `CLAUDE.md`).
- **B10 — `readers` is a required contract field (contracts v2).** Standing access is declared per
  dataset; marketplace grants exist only for roles that are not standing readers. The three-role query
  on `crm.customers` therefore shows the fraud investigator through an approved grant — the bridge from
  claim 2 to claim 6.
- **B11 — The `msisdn` kind means "a phone number", not only a mobile subscriber number.** Since the
  T003 review the detector flags any E.164 number and the three markets' national mobile formats; a
  person's landline is personal data too (GDPR Art. 4(1)), so the wider net follows doctrine 1. The
  kind keeps its name because contracts and catalog already use it. Cost, measured in
  `evals/classification/cases.yaml` → `known_over_flags` (printed by the eval, not failing): 10-digit
  ids starting with 3, digit groups after `00`+country code, German words ending in -ring + number,
  25-year-old dates in free text. **Known misses, accepted for this timebox:** Greek addresses written
  without a street word ("Ερμού 15"), compact `YYYYMMDD` dates, dashed IBANs, and non-European IMSIs
  (inbound roamers: a 15-digit number not starting with 2 is read as an IMEI if its Luhn digit passes).
- **B12 — The custodian writes; it never reads a tag in clear.** Compiled: `roles/bigquery.dataEditor`
  on each contracted dataset for that contract's `custodian`, a seat in every `all_rows` row policy
  (it loads, quarantines and deletes rows), `jobUser`, and **no** Fine-Grained Reader or Masked Reader.
  Quality rules run in the loader on the source before the load (claim 5), so no rule needs a tagged
  column in clear inside BigQuery. gate-proof plants a Fine-Grained Reader for it and the access eval
  refuses it.
- **B13 — Roles bound to a contract field; the reach rules the access eval checks.** `steward` and
  `custodian` have no global seat: on each dataset their seat is that contract's own `steward` /
  `custodian` principal, so crm's stewards govern crm and nothing else. The rules, stated here so the
  eval does not copy them from the compiler: (1) dataset read = `readers` ∪ the custodian (B12) ∪ an
  approved, unexpired marketplace grant for a `grantable_roles` seat; (2) a tagged column is clear only
  with Fine-Grained Reader, masked only with that rule's Masked Reader, otherwise denied; (3) row
  policies cover `readers` ∪ `grantable_roles` ∪ the custodian; a role scoped by the row-access column
  gets one policy per scope, everyone else `TRUE`; (4) a column the estate has and the contract does
  not, and every column of a table with no contract, is tagged `restricted` — no reader at all.
- **B4 (extended) — values the code owns, deliberately not contract fields:** `jobUser` for every seat
  (running a query is not reading data), `require_partition_filter` on partitioned tables (B9),
  `max_time_travel_hours = 48` (the minimum; claim 7), `deletion_protection = false` and
  `delete_contents_on_destroy = true` (deploy → capture → destroy, M4).
