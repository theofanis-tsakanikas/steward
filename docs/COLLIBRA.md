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

## The API subset (read from developer.collibra.com on 2026-10-01)
Source pages: *Working with the Import API v2*, *Importing JSON files*, *Importing assets / domains /
communities*, *The option to continue on error*, *Job results* (all under `/api/guides/import-api/`).

- **Endpoint:** `POST …/import/json-job` (multipart `file`, or a previously uploaded `fileId`); `GET /jobs/{jobId}`
  for the result; the job id is the `id` of the POST response. The REST prefix (`/rest/2.0`) is **assumed** — not
  stated on those pages.
- **Parameters Steward sets explicitly:** `continueOnError=false` (one transaction, rolled back on error; the
  instance default is `false` before Collibra 2026.07 and `true` from it), `sendNotification=false`,
  `relationsAction=REPLACE`, `attributesAction=REPLACE`.
- **Job result:** only state `COMPLETED` with result `SUCCESS` is a sync. `COMPLETED_WITH_ERROR` and `ABORTED`
  mean part of the import was committed — the client raises.
- **Commands:** an array; each `{"resourceType": Community|Domain|Asset, "identifier": {…}, …}`; the implicit
  operation is `MERGE` (create or update by identifier). Commands that depend on others must come after them
  (community, then domains, then assets). Create needs: community `name`; domain `name`, `type`, `community`;
  asset `name`, `type`, `domain` — Steward supplies them through `identifier` and assumes that is enough.
- **Asset identifier:** `{"name", "domain": {"name", "community": {"name"}}}` (or id, or external system/entity id).
  `name` is the unique full name, `displayName` the short one.
- **Attributes:** `{"<type name or id>": [{"value": "…"}]}`. The Import API replaces the types listed and does
  **nothing** to the others — so Steward never omits an attribute of a type (B20).
- **Relations:** `{"<relation type>:<TARGET|SOURCE>": [asset identifiers]}`; the type is an id, `PUBLIC_ID:…`, or the
  fully qualified name `Column:is part of:contains:Table` (no colons in names). With `REPLACE` the list is the
  **complete** final set for the anchor asset and relation type; an empty list deletes.
- **Responsibilities:** `{"<role name or id>": [{"userGroup": {"id": …}} | {"user": {"id": …}}]}`. On a domain
  or community by default; on an asset only if *Asset responsibilities support* is enabled in Collibra
  Console (default off — otherwise an error).
- **What a trial must confirm (T024):** the REST prefix; create-with-identifier-only; the relation types and
  attribute types of the instance's operating model (ids go in `catalog/collibra.instance.yaml`); the group ids;
  read-back (`/assets`, `/attributes`, `/relations`, `/responsibilities`) in the command form `diff()` compares.

## Idempotency and reconciliation
- Every asset's name is a stable key derived from the GCP resource path (`project.dataset.table[.column]`),
  so a second sync is a no-op.
- Reconciliation = three lists: in GCP not in catalog · in catalog not in GCP · in both but differing (the whole
  command: attributes, status, relations, responsibilities — a hand-edited owner shows up), plus two stated
  extras: `pending_first_write` (a log-sink dataset not yet written, B22) and `generated_not_in_catalog`
  (domains, dashboards, terms Steward generates that are not GCP objects). The sync repairs what it owns and
  never deletes (B22).
- Every sync appends to a run log (mode, time, commands, status); a failed one marks the catalog STALE with the
  age of the last good sync, and past 24 h says so (doctrine 1).

## Looker (same rule)
- LookML is parsed from files always (`lkml`). The Looker API (dashboards, usage) is used only with a
  trial (`mode: REAL`); otherwise usage for report expiry is a fixture, labelled.
