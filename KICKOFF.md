# KICKOFF — read this once, at the start of the first session

## Why this exists

The author (Theofanis Tsakanikas, AI & data engineer, Athens) has a **technical interview for a Data
Governance Engineer role on GCP**, expected around **2026-10-07** (about a week after 2026-09-30).
The role, as described by the recruiter: implement and **automate data governance on GCP** —
metadata, lineage, data quality, privacy (GDPR, PII, anonymisation / de-anonymisation, retention),
access; **integrate Looker and Collibra**; automated metadata harvesting and lineage from sources,
ETL/ELT and reports; DQ rules, monitoring and reconciliation dashboards; metadata from owners,
stewards and custodians including reverse-engineering legacy systems; **Data Marketplace**
automation (onboarding, approvals, ownership changes, archival, report expiration).

The author's honest gaps: **Collibra and Looker not used hands-on**; GCP governance services
(Dataplex, DLP, policy tags) known by role, not hands-on. His GCP experience: GKE Autopilot, Kafka,
Spark, BigQuery, dbt, Terraform, Workload Identity (the Realtime Telemetry Pipeline project). His
strongest adjacent work: the Multi-Cloud Governance Platform (one contract drives Unity Catalog
grants and classification on three clouds + Snowflake, PII / least-privilege merge gate, OPA).

**This project turns the gaps into evidence.** In the interview he should be able to say: *"I
haven't used Collibra in production, so I built a governance bridge on GCP to learn its model —
here it is,"* and open a demo that works in three minutes.

The interview context (company, client) is **private**. The repository is public and describes a
**fictional operator** (`CLAUDE.md`, naming rule). Do not put the real client's name anywhere in the repo.

## The deadline and the timebox

- **Timebox: 4–5 working days of build**, finishing **no later than 2026-10-06** — the evening before
  the earliest likely interview date. The author also needs time to prepare; this project must not
  eat that time.
- **Priority order if time runs short** (cut from the bottom): demo works in recorded mode → claims 1,
  2, 4 → claims 3, 5 → claim 6 → claim 7 → live capture of every claim → phase 4 (AI-assisted
  descriptions). A smaller project that is finished and honest beats a larger one that is half-built.

## The budget

- **≤ €50 total** on a dedicated GCP project with billing. Budget alerts at €30 / €50 are created
  **first**. Deploy → capture evidence → destroy. No standing Cloud Composer.

## Collibra and Looker

- The author is requesting a **Collibra trial** (collibra.com) and checking for a **Looker trial** on
  Google Cloud. **Neither is guaranteed.**
- Build against the **documented** APIs behind an adapter. If a trial arrives, pointing the adapter
  at it is configuration. If not, the validating mock is used and **every surface says so** (README
  first line, demo banner, evidence metadata). See `docs/COLLIBRA.md`.
- Looker: LookML files are always parsed (they are plain text); the Looker API is used only if a
  trial exists.

## The demo surface

- **Streamlit** app in `app/`, two modes:
  - **recorded** (default): reads `evidence/` — works with the estate destroyed, works offline, can be
    hosted for free (Streamlit Community Cloud) so there is a **link to send**.
  - **live**: reads the running estate (BigQuery, Dataplex, DLP, mock or real Collibra).
- Pages (each one maps to a line of the job description — see `docs/INTERVIEW.md`):
  1. **Estate & contracts** — datasets, owners/stewards/custodians, classification coverage.
  2. **Privacy** — DLP findings vs contract; the planted PII in innocent-looking columns; the same
     query as three roles (masked / unmasked / row-filtered).
  3. **Lineage** — source → BigQuery → LookML view → explore → dashboard, with unresolved fields and
     unmasked sensitive columns highlighted.
  4. **Data quality** — rules, pass/fail, quarantine with rule ids, source = loaded + quarantined.
  5. **Catalog sync (Collibra)** — the generated payload, idempotency (second run: 0 changes), the
     reconciliation report, mode badge (REAL / MOCK).
  6. **Data Marketplace** — request → named approval → grant with expiry → expired grant flagged;
     unused dashboards → expiry workflow.
  7. **Retention** — declared vs compiled vs evidenced, with the time-travel caveat.
  8. **Gates** — the gate-proof table: every gate, the mutation that breaks it, the refusal.

## How the author wants to work

- Conversation in **Greek**; repository in **English**.
- **Autonomous build.** The session builds, self-reviews (fresh-context subagent), merges its own PRs
  and keeps going without waiting for the author. `stop_at` = a checkpoint entry in `SESSION-LOG.md`
  (Greek), not a pause. The author reviews the finished result.
- **Hard stops only:** before creating any GCP resource (T010+), a DAY-ONE step only the author can
  do, or a doc that is wrong in a way that changes a claim. See `CLAUDE.md` → Git workflow.
- Prefer the portfolio's existing patterns: contracts as the source of truth, `--check` generators,
  planted violations + `gate-proof`, evidence captured live and re-checked offline, deploy → verify →
  destroy. The skills `project-architecture`, `oversight-review` and `readme-standard` apply.

## First session — what to do

1. Read `CLAUDE.md`, `PLAN.md`, `TASKS.md`, then `docs/SCENARIO.md`, `docs/DECISIONS.md`, `docs/INTERVIEW.md`, `docs/COLLIBRA.md`.
2. If anything looks wrong or infeasible in the timebox, decide, record it in `docs/DECISIONS.md`,
   and continue — stop only if it changes a claim (then say so in Greek).
3. Run phases 1 and 2 and the **writing** of phase 3 end to end on the critical path: T000 → … → T022,
   plus all Terraform for T010–T016 written and `terraform validate`-clean. Then **stop** and tell the
   author, in Greek: what is built, what the demo shows, the estimated GCP cost, and the exact
   DAY-ONE inputs needed to apply (project id, billing account, `gcloud auth application-default login`).
4. Keep `SESSION-LOG.md` (Greek) as you go: one entry per closed atom.
