# TASKS — the single source of truth for open work

One block per atom. Closed atoms stay. `closes` must be checkable by a make target, a file or a named
review. Branch names are exact.

**Autonomous build:** `stop_at` = checkpoint entry in `SESSION-LOG.md`, then continue; `review: yes` =
fresh-context subagent review, fix, then self-merge. Hard stop only before creating GCP resources (T010
apply onward) — all phase-3 Terraform is still **written and validated** before that stop.

---

```
id            T000
title         Repository skeleton, toolchain, CI with no cloud
branch        t000-skeleton
depends_on    —
closes        `git init`; pyproject (uv, Python 3.12), ruff, pytest, Makefile with test/lint/evals/check/gate-proof/demo targets
              (empty evals allowed); GitHub Actions CI running them + gitleaks + terraform fmt/validate on an empty infra/;
              `make test lint` green locally
out_of_scope  any domain code; any Terraform resource
stop_at       CI green on the first PR; report in Greek
review        no
status        closed 2026-10-01 — PR #1
```

```
id            T001
title         The fictional operator and the synthetic generator
branch        t001-synthetic
depends_on    T000
closes        `synthetic/` generates (seeded, deterministic) customers, contracts (nested ARRAY<STRUCT>), usage_events
              (partition-ready event_date), network_events, billing, with PII planted in innocent-looking columns
              (`notes_free_text`, `ref_2`) and a ground-truth manifest of where PII was planted that the detector never reads;
              `make synthetic` reproduces byte-identical output twice; docs/SCENARIO.md matches the generated schema
out_of_scope  loading to BigQuery
stop_at       sample of 20 rows per table shown to the author
review        no
status        closed 2026-10-01 — PR #2
```

```
id            T002
title         Contract schema and the first contracts
branch        t002-contracts
depends_on    T001
closes        pydantic contract model (owner/steward/custodian, retention + legal basis, per-column classification, masking per
              role, quality rules, row_access, marketplace); one contract per dataset; `steward validate` rejects missing
              retention/owner (doctrine 3) — tested
out_of_scope  compiling controls
stop_at       contracts reviewed by the author
review        yes
status        closed 2026-10-01 — PR #3 (review + verification pass)
```

```
id            T003
title         Claim 1 — value-based classification and the unclassified-PII gate
branch        t003-classification
depends_on    T001, T002
closes        `core/classify.py` detects MSISDN, IMSI, IMEI, email, IBAN, birth date, address from VALUES (no contract input);
              evals/classification compares detections with the planted manifest (precision/recall reported, n stated) and
              fails the build on a PII column with no tag; name heuristics reported separately; gate-proof mutation:
              remove a tag → the named gate refuses
out_of_scope  calling the real DLP (that is T014)
stop_at       eval report shown
review        yes
status        closed 2026-10-01 — PR #5 with T004 (DECISIONS B7; review + verification pass; gate-proof mutations registered)
```

```
id            T004
title         Claim 2 (compiled side) — controls compiled from contracts
branch        t004-compile
depends_on    T002
closes        `core/compile.py` emits policy-tag taxonomy, masking rules, row access policies, labels, partition expiration
              as Terraform / DDL; `--check` generator; evals/access asserts compiled output == contract implication for
              three roles (analyst / fraud investigator / steward); gate-proof: an unmasked `personal` column for analyst → refused
out_of_scope  applying to GCP
stop_at       compiled output reviewed
review        yes
status        closed 2026-10-01 — PR #5 with T003 (review + verification pass)
```

```
id            T005
title         Claim 5 — quality rules, quarantine, reconciliation
branch        t005-quality
depends_on    T002
closes        rules as code from contracts; quarantine rows carry rule id + row key + run id; source count taken BEFORE rules;
              source = loaded + quarantined asserted; gate-proof: drop a failing row silently → refused
out_of_scope  Dataplex DQ scans (T015)
stop_at       eval green
review        no
status        closed 2026-10-01 — this PR (review: no)
```

```
id            T006
title         Claim 6 — marketplace requests, named approval, expiry
branch        t006-marketplace
depends_on    T002
closes        request → approval by a principal ≠ requester and not a service account → grant with expiry; expired grant
              present → red; "now" taken from evidence capture time; gate-proof: self-approval → refused; SA approval → refused
out_of_scope  real IAM (T016)
stop_at       eval green
review        yes
status        closed 2026-10-01 — PR #7 (review + verification pass)
```

```
id            T007
title         Claim 7 — retention declared, compiled, evidenced
branch        t007-retention
depends_on    T002, T004
closes        dataset without retention → red; compiled partition expiration / lifecycle == contract; retention report's first
              line states the time-travel / fail-safe caveat
out_of_scope  —
stop_at       eval green
review        no
status        closed 2026-10-01 — this PR (review: no)
```

```
id            T008
title         gate-proof runner
branch        t008-gate-proof
depends_on    T003, T004, T005, T006, T007
closes        scripts/gate_proof.py with the three rules (green first · non-zero exit is not evidence · STALE fails); one
              mutation per gate, each naming its gate and the expected phrase; `make gate-proof` green
out_of_scope  —
stop_at       table of mutations shown
review        yes
status        closed 2026-10-01 — PR #9 (review + verification pass)
```

```
id            T009
title         Doctrine 7 — the door with no key
branch        t009-no-key
depends_on    T003
closes        a column with detected personal data declared non-sensitive is refused, and NO waiver/exception mechanism can
              open it (tested: a waiver for it is itself rejected); ADR written
out_of_scope  —
stop_at       ADR reviewed
review        yes
status        closed 2026-10-01 — this PR (review; verification pass recorded in SESSION-LOG)
```

---

```
id            T020
title         LookML project and parser (claim 3, offline)
branch        t020-lookml
depends_on    T001
closes        a small LookML project (≥4 views, 2 explores, 3 dashboards) over the synthetic schema; `adapters/looker.py`
              parses it (lkml) into edges; evals/lineage: unresolved field → red; sensitive column on a dashboard without
              masking → red; cross-check against query-history fixtures (independent of LookML)
out_of_scope  Looker API
stop_at       lineage graph rendered
review        yes
status        closed 2026-10-01 — PR #11 (review + verification pass; make preflight green, gate-proof 39/39)
```

```
id            T021
title         Collibra payload, validating mock, idempotent sync, reconciliation (claim 4)
branch        t021-collibra
depends_on    T002, T020
closes        `adapters/collibra/payload.py` builds communities/domains/assets/relations/responsibilities from contracts +
              harvest; `mock.py` validates request shapes per docs/COLLIBRA.md and rejects unknown types / missing required
              attributes / dangling relations; sync twice → 0 changes; reconciliation report; every output carries mode=MOCK|REAL
out_of_scope  real Collibra (only if a trial exists — T024)
stop_at       reconciliation report shown
review        yes
status        closed (2026-10-01) — built in core/catalog.py + catalog_sync.py rather than payload.py; see SESSION-LOG
```

```
id            T022
title         Streamlit demo, recorded mode, from fixtures
branch        t022-demo
depends_on    T003, T004, T005, T006, T007, T020, T021
closes        `make demo` opens the eight pages in KICKOFF.md from fixtures with no network; a banner states the mode and the
              Collibra mode; every number on a page comes from an evidence file (no hard-coded figures)
out_of_scope  hosting
stop_at       author clicks through all eight pages
review        no
status        closed (2026-10-01) — author click-through of the eight pages still pending (stop_at)
```

```
id            T024
title         Real Collibra / Looker (only if a trial exists)
branch        t024-real-trials
depends_on    T021, DAY-ONE trial access
closes        the same sync runs against the real instance; evidence captured with mode=REAL; docs/COLLIBRA.md updated
out_of_scope  anything that needs a paid licence
stop_at       first real sync result
review        yes
status        open (blocked until a trial exists — expiry 2026-11-03: the interview demo uses the mock regardless; if a trial arrives by then, run the real sync; if not, close as not done, mock stands)
```

---

```
id            T010
title         Bootstrap layer (local apply)
branch        t010-bootstrap
depends_on    T000, DAY-ONE done
closes        terraform bootstrap/: GCS state bucket, Workload Identity pool + provider for the GitHub repo, deployer SA,
              budget alerts €30/€50, required APIs enabled; applied from the laptop once; outputs recorded
out_of_scope  any data resource
stop_at       author confirms budget alerts visible
review        yes
status        closed 2026-10-02 — applied locally (PR #16–#18); 87 resources; org-policy override B53; GitHub variables set
```

```
id            T011
title         Estate layer from CI: datasets, tables, data load
branch        t011-estate
depends_on    T010, T001
closes        BigQuery datasets (EU location), partitioned + clustered tables, nested contracts; synthetic data loaded;
              applied from CI via WIF (no keys); maximum_bytes_billed in every code path
out_of_scope  governance controls
stop_at       row counts match the generator
review        no
status        closed 2026-10-02 — applied from CI via WIF (PRs #19–#21); row counts match the generator
```

```
id            T012
title         Governance layer from CI: policy tags, masking, row policies, labels, expiration
branch        t012-governance
depends_on    T011, T004
closes        compiled controls applied; three role transcripts of one query captured to evidence/access/ with digests
out_of_scope  —
stop_at       transcripts shown
review        yes
status        closed 2026-10-02 — applied from CI; three role transcripts in evidence/live/access.json (masked values, B8 a)
```

```
id            T014
title         DLP inspection (sampled) and comparison with the core detector
branch        t014-dlp
depends_on    T011, T003
closes        DLP findings on row-limited samples captured; core detector vs DLP vs planted manifest reported (n stated);
              disagreements listed, not hidden
out_of_scope  de-identification of full tables
stop_at       comparison shown
review        yes
status        closed 2026-10-02 — live DLP vs planted vs contracts in evidence/live/dlp.json + evals/dlp (n stated, misses listed)
```

```
id            T015
title         Dataplex: lineage, DQ scans, catalog aspects
branch        t015-dataplex
depends_on    T011, T005
closes        BigQuery-job lineage captured from Dataplex; one DQ scan per key table; aspects for owner/classification;
              evidence captured and joined to the offline lineage and quality evals
out_of_scope  Composer / OpenLineage-from-Airflow (deferred)
stop_at       evidence shown
review        no
status        closed 2026-10-02 — DQ scans + job-history lineage captured (evidence/live/dataplex.json, history.json); catalog aspects not written (deferred: owner/classification already live in Collibra payload / contracts)
```

```
id            T016
title         Marketplace live: Analytics Hub listing + IAM grant with expiry + audit sink
branch        t016-marketplace-live
depends_on    T011, T006
closes        one listing; one approved request → IAM binding with Condition expiry; Data Access audit logs sunk to BigQuery;
              an access-review query over them captured
out_of_scope  —
stop_at       evidence shown
review        yes
status        closed 2026-10-02 — listing + expiring IAM grant + audit sink captured (evidence/live/iam.json, audit.json)
```

```
id            T017
title         Evidence check and destroy
branch        t017-evidence-destroy
depends_on    T012, T014, T015, T016
closes        `scripts/check_live.py` (and evals/dlp, evals/dataplex) re-judge every live capture offline; demo Live
              page sits beside the fixture (recorded mode stays the default); spend recorded; destroy run and recorded
out_of_scope  —
stop_at       author confirms the project is empty in the console
review        yes
status        closed 2026-10-02 — live captures re-judged offline; destroy workflow green (`ok sweep: 0`); spend recorded; author confirmed the estate empty in the console (DAY-ONE 10)
```

---

```
id            T030
title         Hosted demo, README, interview script, review
branch        t030-surface
depends_on    T017 (or T022 if phase 3 was cut)
closes        public Streamlit link works with no login; README to readme-standard (first line states MOCK/REAL and that the
              operator is fictional); docs/INTERVIEW.md 3-minute script rehearsed with the author; oversight level-2 review
              findings fixed or deferred with an unlock condition
out_of_scope  phase-4 model proposals unless time remains
stop_at       link sent to the author
review        yes
status        open 2026-10-02 — demo URL live; INTERVIEW dry-run against the URL dated; unlock remaining: speaking rehearsal with the author (D8)
```

```
id            T031
title         (optional) Model-proposed column descriptions, steward accepts/rejects
branch        t031-proposals
depends_on    T030
closes        proposals shown as proposals; acceptance recorded with a named human; nothing applied automatically; a
              proposal can never set classification (gate-proof)
out_of_scope  any automatic apply
stop_at       demo page shown
review        yes
status        open (cut first)
```

---

## Critical path

```
T000 ─► T001 ─► T002 ─┬─► T003 ─► T009
                      ├─► T004 ─► T007
                      ├─► T005
                      └─► T006
        T001 ─► T020 ─► T021 ─────────────┐
   T003..T007 ─► T008 (gate-proof)        │
   T003..T007 + T020 + T021 ─► T022 (demo, recorded, fixtures)  ◄── a demo exists before money is spent
DAY-ONE ─► T010 ─► T011 ─┬─► T012 ─┐
                         ├─► T014 ─┤
                         ├─► T015 ─┼─► T017 ─► T030 ─► (T031)
                         └─► T016 ─┘
T021 + trial ─► T024 (parallel, optional)
```

Parallel once T002 closes: T003 · T004 · T005 · T006 · T020. Phase 3 can start as soon as T010's
day-one prerequisites are done; it does not block the recorded demo.
