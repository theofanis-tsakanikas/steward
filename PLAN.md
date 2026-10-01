# PLAN

Four phases. Each closes on a checkable condition. Open work lives **only** in `TASKS.md`; this file
records what each phase is for, what closed it, and what it cost — as prose, never erased.

Timebox: 4–5 working days, finishing no later than 2026-10-06 (see `KICKOFF.md`).

---

## Phase 1 — the core and the offline claims (day 1–2)

**Purpose.** Everything that needs no cloud: the fictional operator's synthetic data, the contracts,
the pure core, and the evals for claims 1, 2 (compiled side), 5, 6, 7 — plus `gate-proof`.

**Closes when.** `make test evals gate-proof check` is green on a laptop with no credentials; every
gate has at least one mutation refused for the right reason; generators pass `--check`.

Closed in this phase: —
Open: see `TASKS.md` (T000–T009).

---

## Phase 2 — the integrations, offline (day 2–3)

**Purpose.** LookML parsing and lineage (claim 3, offline half), the Collibra payload builder, the
validating mock and the reconciliation (claim 4), and the **Streamlit demo in recorded mode** fed by
fixture evidence — so that a demo exists **before** any money is spent.

**Closes when.** `make demo` opens all eight pages from fixtures; `make evals` covers claims 3 and 4;
the Collibra sync is idempotent (second run: 0 changes) against the mock.

Closed in this phase: —
Open: see `TASKS.md` (T020–T029).

---

## Phase 3 — the estate and the evidence (day 3–4)

**Purpose.** Terraform the GCP estate (bootstrap locally; estate, governance and marketplace layers
from CI via Workload Identity Federation), load the synthetic data, apply the compiled controls, run
DLP and Dataplex, capture **live evidence** for every claim into `evidence/`, verify it offline, then
**destroy**.

**Closes when.** `evidence/` holds a capture per claim with digests; `make evidence-check` re-verifies
them offline; the demo switches from fixtures to captured evidence; spend ≤ €50; the estate is
destroyed and the destroy is recorded.

Closed in this phase: —
Open: see `TASKS.md` (T010–T019).

---

## Phase 4 — the surface and the story (day 5, cut first if late)

**Purpose.** Host the recorded demo (Streamlit Community Cloud), README to the portfolio standard,
the 3-minute demo script and honest lines in `docs/INTERVIEW.md`, an oversight-level-2 review in
fresh context. Optional, only if time remains: model-**proposed** column descriptions that a steward
accepts or rejects (doctrine 5), shown as proposals, never applied automatically.

**Closes when.** A public demo link opens in a browser with no login; README passes `readme-standard`;
the review's findings are fixed or recorded as deferred with an unlock condition.

Closed in this phase: —
Open: see `TASKS.md` (T030–T039).

---

## What this plan will not do

- It will not connect to any real company's systems or use any real personal data.
- It will not claim a real Collibra or Looker integration unless a trial instance actually accepted
  the calls; the mode is stated on every surface.
- It will not keep a standing GCP estate or a standing Cloud Composer environment.
- It will not let a model classify, grant, approve or apply anything.
- It will not claim immediate erasure (BigQuery time travel / fail-safe).
- It will not exceed the timebox to add scope; scope that does not fit goes to "Deliberately deferred".
