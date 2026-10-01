# COLLIBRA — the model, the API subset, and the real-vs-mock rule

## The rule
The adapter speaks Collibra's **documented** REST API. Two modes, chosen by configuration:
- **REAL** — a trial instance exists (DAY-ONE step 7); evidence is captured with `mode: REAL`.
- **MOCK** — a local mock that **validates** every request against the shapes below and rejects
  unknown asset types, missing required attributes and relations to assets that do not exist.
Every output (payload, sync report, reconciliation, demo banner, README first line) carries the mode.
Saying "integrated with Collibra" while running the mock is a defect.

## The model (what the payload builds)
- **Community** → **Domain** → **Asset**. Assets have a **type** (e.g. Database / Schema / Table / Column,
  Report, Business Term, Data Set), a **status**, **attributes** (e.g. Description, classification)
  and **relations** (e.g. column *is part of* table; report *uses* table; business term *is represented by* column).
- **Responsibilities**: user/group ↔ role (Owner, Steward, Custodian) on an asset or domain.
- **Workflows**: approvals (access request, onboarding, ownership change). In MOCK mode the workflow
  is simulated by Steward's own marketplace flow and labelled as such.

## The API subset (to verify against the developer documentation before coding)
- Core REST v2 resources for communities, domains, assets, attributes, relations, responsibilities.
- The **Import API** (bulk JSON job) for idempotent upserts keyed on a stable external identifier.
- Type and relation-type **identifiers differ per instance / operating model** → a config file maps
  Steward's names to the instance's IDs; the mock ships a default map.
- First session: read the current Collibra developer documentation, record the exact endpoints and
  required fields here with the date read, and make the mock's validation match them.

## Idempotency and reconciliation
- Every asset carries a stable external key derived from the GCP resource path (`project.dataset.table[.column]`),
  so a second sync is a no-op.
- Reconciliation = three lists: in GCP not in catalog · in catalog not in GCP · in both with differing attributes.

## Looker (same rule)
- LookML is parsed from files always (`lkml`). The Looker API (dashboards, usage) is used only with a
  trial (`mode: REAL`); otherwise usage for report expiry is a fixture, labelled.
