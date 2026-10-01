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
- **B5 — Only `CONTRACT_MISSING` and `TABLE_UNDECLARED` are waivable (allowlist), for at most 90 days,
  approved by a member of `group:privacy-office` who is neither the requester nor an owner of the
  waived dataset.** A waiver that could suppress a missing owner, retention or classification would be
  doctrine 3 with a deadline attached. Found by the T002 hostile review (finding 1).
