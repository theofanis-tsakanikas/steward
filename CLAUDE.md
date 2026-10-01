# Steward

*Steward* — the data-governance role (the person who keeps a dataset's meaning, quality and
access honest) and the plain word for one who looks after something that is not theirs.

> **A governance layer for a telco's BigQuery estate. A column that holds personal data without a
> policy tag, an owner and a retention period is a build failure — and the catalog is generated
> from the estate, never hand-maintained.**

---

## Read this first, every session

| File | What it is | When |
|---|---|---|
| `KICKOFF.md` | Why this project exists, who it is for, the deadline, the first session's instructions | First session only, then on demand |
| `CLAUDE.md` (this file) | The mental model, the claims, the doctrine, the rules | Every session |
| `PLAN.md` | Four phases, what closes each, what this plan will not do | Every session |
| `TASKS.md` | **The single source of truth for open work.** Atoms with `closes` / `stop_at` | Every session, before touching code |
| `docs/SCENARIO.md` | The fictional operator, the data, the decision paths, what makes it hard | Before writing data or contracts |
| `docs/DECISIONS.md` | Scope · Technology · Method · Deliberately deferred | Before any technology choice |
| `docs/INTERVIEW.md` | The job posting mapped to features, the 3-minute demo script, the honest lines | Before building the demo surface |
| `docs/REGULATORY.md` | GDPR / ePrivacy posture, argued, with what still needs verifying | Before writing anything that states a legal fact |
| `docs/GCP-CONSTRAINTS.md` | Service limits, costs, what needs billing, what has no Terraform | Before writing Terraform |
| `docs/DAY-ONE.md` | Manual steps with no API, done by the author, recorded | Before the first apply |
| `docs/COLLIBRA.md` | The Collibra model, the API subset the adapter uses, real-vs-mock rule | Before writing the adapter |
| `SESSION-LOG.md` | Checkpoint log in Greek, one entry per closed atom (autonomous build) | After every closed atom |

**Language rule:** all repository content in **English**; conversation with the author in **Greek**.

**Naming rule (non-negotiable, public repository):** the operator is a **fictional European
mobile and fixed-line operator** — never any real company's name, logo, colours,
customer data or internal terms. The interview it was built for is context in `KICKOFF.md`, not
content of the repository. A demo that looks like it came from inside a real company is a
liability, not a credential.

---

## What this system does (the mental model)

A telco's data lands in BigQuery: customers, contracts, usage events, network events, billing.
Analysts query it, Looker dashboards are built on it, and a business catalog (Collibra) is meant to
describe it. In real companies the three drift apart within a month: a new column holds an MSISDN
and nobody tagged it; a dashboard reads a table nobody knows exists; the catalog says a dataset is
owned by someone who left.

Steward makes the estate **declare itself** and makes drift **a failing build**:

1. **Contracts** (YAML, one per dataset) declare owner, steward, custodian, classification per
   column, retention, quality rules, and who may request access.
2. **The core** (pure Python) compiles contracts into the controls GCP enforces — policy tags,
   masking rules, row access policies, labels, partition expiration, quality rules — and
   **checks the estate against them**: DLP findings, `INFORMATION_SCHEMA`, lineage, LookML.
3. **Adapters** (thin) talk to GCP, Looker and Collibra. The Collibra catalog is **generated**
   from contracts + harvested metadata + lineage, upserted idempotently, and reconciled.
4. **The demo** (Streamlit) shows it to a human in three minutes, from **recorded evidence** when
   the estate is down and **live** when it is up.

### The boundary this system is built around

| Statistical models own (optional, phase 4) | Deterministic code owns |
|---|---|
| **Proposing** a column description or a glossary term from a sample, for a steward to accept or reject | Whether a column is sensitive (DLP findings + contract; uncertainty = sensitive) |
| — | Every control applied: policy tags, masking, row policies, expiration, IAM |
| — | Every lineage edge (from jobs, Dataplex and parsed LookML — never inferred by a model) |
| — | Every quality verdict and where a failing row goes |
| — | Whether an access request is granted, by whom, until when |
| — | Every catalog asset and relation written to Collibra |

The test for every item: **is there exactly one correct answer here?** If yes, it is code. A model
may draft a description; it may never classify, grant, or approve — doctrine rule 5.

---

## The seven claims

Provable **in CI, on a laptop, with no GCP account and no credentials** — except where a claim
says otherwise, and then the provable part lives in `core/` and the live part is **captured
evidence** (`evidence/`) re-checked offline.

| # | Claim | Proved by |
|---|---|---|
| **1** | **No sensitive column is unclassified.** A column whose *values* DLP-style detectors flag as personal data (MSISDN, IMSI, IMEI, email, IBAN, birth date, address) and that carries no policy tag in the contract fails the build. *Trap:* a detector that reads the contract to decide what is sensitive, compared with a contract that says the same, is one function agreeing with itself — so the detector reads **values only**, the synthetic generator plants PII in columns whose names do not reveal it (`notes_free_text`, `ref_2`), and the contract is never an input to detection. Name-based heuristics are reported separately and never count as proof. | `evals/classification/` |
| **2** | **Same query, different answer, by role.** Contracts compile to BigQuery policy tags, data-masking rules (hash, nullify, last-four) and row access policies; an analyst, a fraud investigator and a steward running one query see three different, declared results. *Not claimed offline:* that BigQuery enforces them — offline proves the **compiled DDL / Terraform** is exactly what the contract implies; the enforcement is captured live (three role transcripts) and its digests checked in CI. | `evals/access/` + `evidence/access/` |
| **3** | **Lineage reaches the dashboard, and every dashboard field resolves.** Edges from BigQuery job metadata and Dataplex lineage are joined to edges parsed from LookML (view → table, explore → views, dashboard → fields); a Looker field that resolves to no catalogued column, and a catalogued sensitive column reaching a dashboard without masking, both fail. *Trap:* comparing LookML-derived lineage with itself proves parsing, not truth — so dashboard → table edges are cross-checked against **independent** query history (`referenced_tables`), and a disagreement is a finding, not a merge. | `evals/lineage/` |
| **4** | **The catalog is generated, idempotent and reconciled.** The Collibra payload (communities, domains, assets, relations, responsibilities) is built from contracts + harvest; running the sync twice changes nothing; a reconciliation report lists what exists in GCP but not in the catalog and vice versa. *Trap:* a mock that accepts anything proves nothing — the mock **validates every request against the documented Collibra request shapes** and rejects unknown asset types, missing required attributes and dangling relations. *Not claimed unless a trial exists:* that a real Collibra instance accepted it — `docs/COLLIBRA.md` states which mode the evidence came from. | `evals/catalog/` |
| **5** | **A failing row is quarantined with its rule and routed to its owner, never dropped.** Quality rules live in the contract (completeness, validity, uniqueness, freshness, referential integrity); failures land in a quarantine table with rule id, row key and run id; source count = loaded + quarantined, always. *Trap:* a reconciliation computed from the loaded table alone reconciles trivially — counts are taken from the source **before** the rules run. | `evals/quality/` |
| **6** | **Access is requested, approved by a named human, and expires.** Marketplace requests become IAM grants only after an approval by a principal who is not the requester and not a service account; every grant carries an expiry (IAM Condition); an expired grant still present in the estate turns CI red. *Trap:* testing expiry with a clock the code also controls is a tautology — the evaluator takes "now" from the evidence capture timestamp, not from the code under test. | `evals/marketplace/` |
| **7** | **Retention is declared, enforced and evidenced.** Every dataset declares a retention period and legal basis; partition expiration and bucket lifecycle are compiled from it; a dataset without one fails. *Not claimed:* immediate erasure — BigQuery time travel and fail-safe keep data recoverable for up to ~14 days, and the retention report says so in its first line. | `evals/retention/` |

**Claim 1 is the one that separates this from a demo. Claim 4 is the one nobody builds** — every
governance talk shows a catalog; almost nobody shows a catalog that can prove it matches the estate.

`gate-proof` breaks each gate on purpose and requires the **named** gate to refuse it, for the right
reason: **green first · a non-zero exit is not evidence · a mutation whose target has moved is
STALE, not passed.**

---

## The doctrine

Seven rules that decide every failure-handling question. Each becomes an ADR in `docs/adr/`.

1. **The safe state is "treat it as sensitive and deny".** A column of unknown sensitivity is
   masked; an access request with no decision is denied; a classification conflict between DLP and
   the contract resolves to the stricter one. Over-masking is a cost (an analyst opens a request);
   under-masking is a breach. *But the catalog is not safety:* if the Collibra sync fails, BigQuery
   keeps working and the catalog shows a **stale** marker with its age — fail closed on privacy,
   fail open (loudly, with a deadline) on documentation.
2. **Every control is visible where it acts.** A masked value says it is masked; a quarantined row
   says which rule; a catalog entry says when it was last reconciled and from which mode (real
   Collibra or mock). A control nobody can see is a control nobody can audit.
3. **A default is never invented.** No default owner, no default retention, no default
   classification of "public". A missing declaration is a failing build, not a plausible value.
4. **A correction never erases what was previously stated.** A contract change is a new version;
   the catalog keeps the previous description and classification with their dates.
5. **Nothing approves itself.** No pipeline, model or service account approves an access request,
   lowers a classification, clears a quality finding or accepts its own drafted description.
6. **Exceptions expire.** A waiver (e.g. a legacy table with no owner yet) has an expiry date; on
   expiry the finding returns and CI goes red.
7. **One door has no key: a column in which personal data was found cannot be declared
   non-sensitive by anyone.** An approver would have nothing to approve *with* — the values are the
   evidence. The only way out is to remove the data, and the scan must then come back clean.

---

## Non-negotiable engineering rules

- **Framework-free core.** All domain logic in `src/steward/core/` as pure functions over plain data
  (contracts, findings, metadata rows, LookML trees). No `google.cloud`, no Collibra client, no
  Streamlit import in `core/`. Adapters are thin and call the core.
- **Offline is the default.** Full suite, every eval, every gate, `terraform validate`, the demo in
  recorded mode — with no GCP account. GCP is where evidence is captured, not where logic is validated.
- **IaC only.** Terraform for every GCP resource (`google` / `google-beta` providers). No console
  clicks. Anything with no API or no Terraform resource goes in `docs/DAY-ONE.md`, done once by the
  author, recorded.
- **Bootstrap is local, everything else is CI.** The bootstrap layer (state bucket, Workload Identity
  pool, deployer service account, budget) is applied from a laptop once; every other layer from CI.
- **No long-lived keys.** **Workload Identity Federation** from GitHub Actions; no service-account
  JSON keys anywhere; `gitleaks` on every push.

Deliberately not adopted from the AWS projects: AgentCore, Bedrock, OIDC to AWS — wrong cloud.
Cloud Composer is **not** a standing resource (cost); see `docs/DECISIONS.md`.

---

## Repository layout (target — the first session creates it, this file does not)

```
contracts/            one YAML per dataset: owners, columns + classification, retention, DQ rules, access policy
synthetic/            the generator for the fictional operator's data (seeded, deterministic)
lookml/               a small LookML project (views, explores, dashboards) over the synthetic estate
src/steward/
  core/               pure functions: classify, compile_controls, lineage, reconcile, quality, marketplace, retention
  adapters/
    bigquery.py       INFORMATION_SCHEMA, jobs, DDL apply
    dlp.py            Sensitive Data Protection inspection / de-identification
    dataplex.py       lineage, DQ scans, catalog aspects
    looker.py         LookML parse (always) + Looker API (if a trial exists)
    collibra/         client.py (real REST) · mock.py (validating mock) · payload.py (pure, in core's terms)
  cli.py              steward plan | apply | scan | sync | reconcile | evidence
app/                  Streamlit demo: recorded mode (default) and live mode
evals/                one directory per claim
evidence/             captured live runs (JSON + digests), re-checked offline
infra/                terraform: bootstrap/ · estate/ · governance/ · marketplace/
scripts/gate_proof.py
docs/                 SCENARIO, DECISIONS, INTERVIEW, REGULATORY, GCP-CONSTRAINTS, DAY-ONE, COLLIBRA, adr/
```

---

## The contract layer

One YAML per dataset is the single source of truth. Everything else — policy tags, masking rules,
row policies, labels, expiration, DQ rules, catalog assets, the data dictionary in the README — is
**generated** from it and checked with `--check` in CI (regenerate in memory, fail if it differs from
what is committed). A contract declares, at minimum:

- `dataset`, `owner`, `steward`, `custodian` (named groups, not individuals' emails in public)
- `retention` (period + legal basis) — required, no default
- per column: `type`, `description`, `classification` (`public` / `internal` / `personal` /
  `special` / `sensitive-network`), `masking` for each role, `quality` rules
- `row_access` (which role sees which rows, e.g. by `country`)
- `marketplace`: listable or not, who may approve, maximum grant duration

A field in a contract that no generator reads is a defect; a generated control with no contract
field behind it is a defect.

---

## Cost controls — always active

- **Budget alerts at €30 and €50** on the project, created in the bootstrap layer **before** anything else.
- **One dedicated GCP project**, everything labelled `project=steward`; `make destroy` (or deleting
  the project) removes all of it. Deploy → capture evidence → destroy. The demo runs from evidence.
- **BigQuery:** `maximum_bytes_billed` on every query the code runs; `require_partition_filter` on
  large tables; synthetic data kept to low single-digit GB.
- **DLP:** inspect samples (row limits), never full tables.
- **Dataplex scans:** on small tables, on demand, not scheduled hourly.
- **No standing Cloud Composer.** If OpenLineage-from-Airflow is wanted, one environment for one
  day, then destroyed — recorded in `docs/DECISIONS.md` with its cost.
- Target total spend for the whole project: **≤ €50**.

---

## Git workflow — autonomous build (decided by the author, 2026-10-01)

This is a demo, not a client system. The session works **without waiting for the author** and
the author reviews the finished result. So:

- Private GitHub repo. One branch per task atom (`TASKS.md` gives the name); small commits with
  evidence in the message (what changed, which make target proves it, what is still open).
- The session **opens the PR, waits for CI green, and merges it itself** (squash or rebase), then
  continues with the next atom on the critical path. No author approval per PR.
- `stop_at` in `TASKS.md` means a **checkpoint**, not a pause: write a short entry in `SESSION-LOG.md`
  (in Greek: what closed, which target proves it, what is open) and continue.
- `review: yes` means: run an **oversight level-2 review in fresh context** (a subagent that has not
  seen the work, per the `oversight-review` skill), fix its findings, record them in `SESSION-LOG.md`,
  then merge. The author is not the reviewer during the build.
- CI on every PR: lint, tests, evals, `--check` generators, `gate-proof`, `terraform validate`, `gitleaks`.

**The only hard stops** — the session stops and tells the author, in Greek, exactly what is needed:
1. **Before any `terraform apply` or any call that creates or costs GCP resources** (T010 onward).
   Everything up to that point — all Terraform written, `terraform validate` / `plan`-ready, every
   offline claim, the demo in recorded mode from fixtures — is built and checked first.
2. A manual step from `docs/DAY-ONE.md` that only the author can do (billing, credentials, trials).
3. Something in the docs that is wrong or infeasible within the timebox and changes a claim.
Everything else is decided, recorded in `docs/DECISIONS.md`, and done.

---

## Before any change — checklist

- Which of the seven claims does this serve?
- Is there exactly one correct answer here? Then it is code, not a model.
- Can it be validated with no GCP account? If not, what is captured as evidence, and how is it re-checked offline?
- If it is a gate: is there a `gate-proof` mutation that proves it bites, for the right reason?
- If it touches a contract: is the change a new version, and does every generated artefact regenerate?
- Does anything in this change name a real company, use real data, or look like it came from inside one?
- If it states a legal fact: which article, which instrument, verified when?
- Does it fit the timebox in `KICKOFF.md`? If not, it goes to "Deliberately deferred" with an unlock condition.
