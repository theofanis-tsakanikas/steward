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
  the BigQuery dataset description (T008, doctrine 2) and the catalog attribute (T021) · `marketplace.listable`, `max_grant_days`, `grantable_roles`,
  `approvers` → marketplace flow (T006) · `retention.mode/column/rule` → compiled partition expiration
  and scheduled DELETE (T007) · `kinds` → role ceilings (T004) and the classification gate (T003) ·
  `masking` → policy tags and data policies (T004) · `quality`, `freshness` → rules engine (T005) ·
  `row_access` → row access policies (T004). `scripts/check_contract_fields.py` (T008) now enforces it: a
  field no generator or gate reads is FIELD_UNREAD; documentation-only fields are listed in that script.
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
  refuses it. dataEditor does not include `bigquery.tables.setCategory` (only dataOwner and admin do;
  BigQuery IAM docs, read 2026-10-01), so the custodian cannot untag a column to read it. **Open:** an
  erasure keyed on a tagged column (a customer key) cannot run as the custodian; erasure by tagged key
  needs its own decision before it is claimed (claim 7 does not claim it).
- **B13 — Roles bound to a contract field; the reach rules the access eval checks.** `steward` and
  `custodian` have no global seat: on each dataset their seat is that contract's own `steward` /
  `custodian` principal, so crm's stewards read crm and nothing else. (At tag level a steward may hold a
  Masked Reader on a tag another dataset's columns also carry — tags are shared by identical profiles —
  but without dataset access that grant reaches nothing; the eval checks both levels.) The rules, stated here so the
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
- **B14 — The quarantine table (claim 5).** For every contracted table with at least one quality rule,
  the compiler emits `<table>__quarantine`: the source schema with the source's policy tags (the payload
  is the same personal data), plus six untagged metadata columns — `_run_id`, `_rule_ids`, `_row_key`,
  `_routed_to`, `_failures`, `_quarantined_at` — and the source table's row access policies (an analyst
  must not read another country's quarantined rows). It has no partition expiry: it is emptied by repair,
  not by the calendar. The contracts gate does not report it as an undeclared table.
- **B15 — A dataset filled by a log sink has a contract without tables.** The `audit` dataset holds
  BigQuery Data Access audit logs — principals' e-mail addresses — so it is governed like any other: owner,
  steward, custodian, lawful basis, retention (90 days, compiled as the dataset's default partition
  expiration because Logging creates the partitioned tables), standing readers (its steward only), not
  listed. What it does not do is enumerate columns: Cloud Logging creates and owns the tables on first
  write. The contract declares `log_sink.personal_kinds: [email]`; the classification gate accepts those
  kinds there (info) and blocks any other; the drift check does not report Logging's tables as undeclared.
  Kept narrow so it is not a key to doctrine 7: only tables named `cloudaudit_googleapis_com_*` are exempt
  (any other table in the dataset is undeclared), `personal_kinds` may only be `[email]`, exactly one
  contract may declare a sink (LOG_SINK_DUPLICATE), and the writer identity allowed `dataEditor` is the
  one captured with the IAM snapshot, not any logging service account.
  Column-level tags on sink-created tables are **not** claimed. Found by the T006 review.
- **B16 — A marketplace grant goes to the person who asked, and only a member of the seat may ask.**
  `_roles.yaml → seat_groups` names the directory group behind each requestable seat; a request from
  anyone outside it is REQUESTER_NOT_IN_SEAT, and the compiled IAM binding is the requester's own principal
  (`var.grantees["user:…"]`, a variable distinct from governance's seat-keyed `principals`, whose values
  must be `user:` or `serviceAccount:` — never a group), not the seat's. Seat membership is the
  hand-declared `directory` in `_roles.yaml`, not Cloud Identity: offline it is checked against that file. Principals compare case-insensitively. The ledger is a
  strict model (integer days > 0, unique ids, decisions only for known requests); an invalid ledger grants
  nothing. A decision later than `max_grant_days` after its request is stale. `finance` is not listed
  (contract v3): it is reached by standing readers only. Found by the T006 review.
- **B17 — The core reads no clock.** `scripts/check_core_purity.py` refuses a `time` import and any
  attribute reference to `now`, `today`, `utcnow`, `fromtimestamp`, `time_ns`, `monotonic` or
  `perf_counter` under `src/steward/core/` (CORE_CLOCK). It catches mistakes, not malice: `__import__`,
  `importlib`, `getattr` with a built string or shelling out to `date` would pass it. "Now" is data: a capture timestamp, a ledger's `as_of`, the
  synthetic anchor. Replaces a narrower AST test the T006 review showed could be bypassed.
- **B18 — What the lineage cross-check proves offline, and what it does not.** The job history
  (`evals/lineage/query_history.json`) is a hand-written fixture written *after* the LookML: its clean
  agreement with LookML is constructed, and only the planted drift exercises the comparison. Independence
  needs real Looker query jobs in `INFORMATION_SCHEMA.JOBS`, i.e. a Looker instance (D3); without one, any
  "live" history is still SQL compiled from this LookML. The `looker_dashboard` job label is this
  fixture's convention; how a real Looker marks its queries (labels or the SQL context comment) is
  **unverified** and must be read from a live instance before T015 relies on it. What *is* proved offline:
  every dashboard reference resolves or fails closed (raw SQL, alias.column, unsupported LookML), tagged
  columns are judged per connection role leaf by leaf, and every dashboard table traces back to a landing
  source in the history. Dashboards the history knows and LookML does not are blocking
  (`LINEAGE_UNMODELLED_DASHBOARD`); history older than 30 days is ignored.
- **B19 — A hashed direct identifier on a dashboard is reported, not refused.** SHA-256 of an MSISDN, IMSI,
  IMEI, e-mail or IBAN is pseudonymised data (GDPR Art. 4(5)): enumerable, so reversible. It is acceptable
  as a join key and is reported as `PSEUDONYMISED_ID_ON_DASHBOARD` (warn) wherever it is displayed — the
  pseudonymisation-vs-anonymisation line the interview rehearses (scenario 158).
- **B20 — The catalog payload follows the Import API guide as read on 2026-10-01, which changed four things
  the first draft assumed.** (1) A relation key is the fully qualified form
  `Column:is part of:contains:Table:TARGET` (or an id / `PUBLIC_ID:` form), not `is part of:TARGET`.
  (2) A responsibility names a role and a user group **by id** (`{"userGroup": {"id": …}}`); a group name is
  not accepted. (3) Responsibilities live on the **domain**: asset-level responsibilities are off by default
  in Collibra Console and an import that sets them errors — the mock behaves like the default, and each
  dataset's domain carries Owner / Steward / Custodian. (4) With `attributesAction=REPLACE` the Import API
  leaves attributes a command omits, so a value that stops applying (a column's "Proposed Classification"
  once a contract declares it) would stay in the catalog and be read as current: every asset of a type
  always carries the same attribute set and an expired value is overwritten with an explicit "none". The
  client states `continueOnError=false` itself because the instance default changed in Collibra 2026.07
  (`true` from then), and treats only `COMPLETED`/`SUCCESS` as a sync — `COMPLETED_WITH_ERROR` and `ABORTED`
  committed part of it. **Not confirmed:** the `/rest/2.0` prefix, whether a create needs top-level
  `name`/`domain` beside `identifier`, and the relation types themselves (Steward's own vocabulary; an
  instance maps them in `catalog/collibra.instance.yaml`). T024 settles these.
- **B21 — "Last reconciled" is a property of the run, not of the asset.** Writing a timestamp on every
  asset every run would make a second sync "change" everything. Instead: `Last Changed` is stamped only on
  assets whose content changed; every run — including one that sent nothing, and one that failed — is
  appended to the mock's run log with its mode; the community and every domain description say
  `catalog mode: MOCK|REAL`; the STALE marker is computed from the run log. The catalog entry therefore
  shows when it last *changed* and from which mode; when it was last *reconciled* is in the sync report and
  the demo's Catalog page. (Doctrine 2 asks that a catalog entry say when it was last reconciled; this is the
  closest reading that keeps claim 4's idempotency, and it is stated here rather than hidden.)
- **B22 — The catalog never deletes.** An asset in the catalog that GCP no longer has is listed by the
  reconciliation (`in_catalog_not_in_gcp`) and stays until a human retires it (doctrine 4). A dataset whose
  tables a log sink creates on first write (B15) is catalogued before they exist and listed under
  `pending_first_write` instead of as drift; once the sink writes, the live harvest contains it.
- **B23 — Directory ids are derived, fictional, and the mock's only source of identity.** The 10 contract
  groups map to `uuid5` ids in `catalog/collibra.yaml`; a contract naming a group not listed stops the build
  (`OWNER_GROUP_UNKNOWN`). Steward assigns groups, never individual users: the mock refuses `user`.
- **B24 — The diff compares only what Steward owns.** `_owned(stored, want)` restricts the comparison to the
  attributes, relation types and responsibilities Steward writes. A foreign attribute, relation or
  responsibility added in Collibra is *reported* by `reconcile` (`in_both_differing`) and never resent
  forever, so a second sync of an unchanged estate sends 0 commands. `Last Changed` is stamped only on
  changed assets and is not content.
- **B25 — Human-owned fields are never overwritten.** A Business Term is proposed as `Candidate` (or
  `Under Review` when two definitions conflict); a steward accepts it in Collibra and the sync leaves its
  `status` alone (`HUMAN_OWNED`). A term born `Accepted` fails the gate (`CATALOG_SELF_ACCEPTED`, doctrine 5).
- **B26 — Review findings accepted rather than fixed (T021 level-2 review, 2026-10-01).**
  (a) The claim-1 conflict on *contracted* columns is owned by `steward scan`, not by the catalog; the catalog
  only reports "Not scanned" for undeclared columns with no detection run, never "no personal data found".
  (b) The mode (`MOCK|REAL`) is stated in the community and domain descriptions and in every report, not on
  every asset: Collibra has no per-asset provenance field and an extra attribute would be one more thing to
  reconcile. (c) A change of an existing asset's type is not refused by the mock: Collibra's guide allows it.
  (d) The cardinality of multi-value attributes is assumed from the guide, not observed on an instance.
  (e) The operating model in `catalog/collibra.yaml` is Steward's own, not read from a real instance;
  T024 is where that is tested, if a trial exists.
- **B27 — `pending_first_write` expires.** A log-sink dataset (`audit`, B15) has no table until the first
  write; the reconciliation lists it as pending, not missing, until `pending_first_write_until`
  (2026-10-31, doctrine 6), judged by the run's own `at` timestamp because `core/` reads no clock.
