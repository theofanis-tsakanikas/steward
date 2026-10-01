# SCENARIO — the fictional operator

## The operator
A **fictional** European mobile and fixed-line operator, active in three countries (GR, IT, DE).
The first session picks its name: obviously fictional, checked not to be an existing operator or a
well-known sample brand. Never a real company's name, logo, colours or terms.

Its data platform is on GCP: data lands in BigQuery (EU), analysts and Looker dashboards read it,
and a business catalog (Collibra) is supposed to describe it. A new governance team must make the
estate declare itself and keep the catalog honest. Steward is that team's tooling.

## The data (synthetic, seeded, deterministic)
The operator is **Halverra Telecom** (fictional; see `docs/DECISIONS.md` B1). `synthetic/generate.py`
(seed `20261001`, anchor date 2026-09-30) writes these tables; `synthetic/data/_schema.json` is the
authoritative schema and this table is checked against it by hand at every schema change.

| Table | Rows | Grain | Interesting columns | Why it is hard |
|---|---|---|---|---|
| `crm.customers` | 600 | one row per customer | `customer_id`, `full_name`, `email`, `msisdn`, `birth_date`, `address` (STRUCT street/city/postcode), `country`, `segment`, `consent` (STRUCT marketing/profiling/updated_at), `created_at` | direct identifiers; nested address; consent as data |
| `crm.customers.contracts` | 1–3 per customer | ARRAY<STRUCT> inside `customers` | `contract_id`, `plan`, `start_date`, `end_date`, `status`, `monthly_fee` | nested one-to-many; UNNEST double-counting trap |
| `crm.support_tickets` | 400 | one row per ticket | `ticket_id`, `customer_id`, `notes_free_text`, `ref_2`, `country` | **PII planted in free text (~22% of notes: MSISDN, email, birth date, IBAN) and in `ref_2` (~80% MSISDNs)** — claim 1's trap |
| `network.usage_events` | 6,000 | one row per event, partitioned by `event_date`, clustered by `msisdn`, `cell_id` | `msisdn`, `imsi`, `cell_id`, `country`, `event_type` (voice/sms/data), `volume_mb`, `duration_s` | **traffic and location data** — a stricter category (ePrivacy), not only GDPR |
| `network.network_events` | 3,000 | one row per device attach, partitioned by `event_date` | `imei` (Luhn-valid), `imsi`, `cell_id`, `country`, `rat` | device identifiers that look like plain numbers |
| `finance.billing` | 1,802 | one row per invoice, partitioned by `issue_date` | `invoice_id`, `customer_id`, `iban` (valid mod-97), `amount`, `due_date`, `country` | financial identifiers; retention driven by tax law; planted defects (negative amounts, orphan customers, two duplicate invoices) |
| `legacy.legacy_crm_export` | 150 | one undocumented table | `k_id`, `nm_1`, `tel_a` (spaced `0030 …` numbers), `fld_7` (IBAN), `dt_x` (DD/MM/YYYY birth dates), `adr_l1`, `cd_s`, `upd` | scenario 161: reverse-engineering metadata from a legacy system; no contract |

Identifiers are random numbers in the right *shape* with real check digits (IBAN mod-97, IMEI Luhn).
MCCs are the real country codes; MNCs are `97`, chosen to be unlikely to name a real network (not
verified against the ITU list). E-mail domains are the reserved `example.*` domains.

The generator also writes `synthetic/_planted.json`: where PII was planted. **The detector never reads it**; only the eval does.

## Roles (who sees what)
| Role | Sees | Does not see |
|---|---|---|
| **Analyst (country)** | aggregates, masked identifiers (hash / last four), only their country's rows | raw MSISDN / IMSI / IMEI / email / IBAN |
| **Fraud investigator** | raw device and line identifiers for all countries, every read audited | free-text notes, IBAN |
| **Data steward** | metadata, descriptions, quality results, masked values | raw identifiers |
| **Custodian / pipeline SA** | writes data, applies controls | approve anything (doctrine 5) |

## Decision paths and their safe states
| Path | Decision | Horizon | Safe state |
|---|---|---|---|
| Classification | is this column personal / special / network-sensitive? | per scan | treat as sensitive, mask |
| Access | may this principal read this dataset, until when? | per request | deny; grants always expire |
| Quality | does this row load or go to quarantine? | per run | quarantine with rule id, never drop |
| Catalog | does the catalog match the estate? | nightly | catalog marked **stale** with age; BigQuery unaffected |
| Retention | must this partition be deleted / anonymised? | daily | delete per contract; caveat time travel |
| Report lifecycle | is this dashboard still used? | weekly | notify owner → archive after N days, never delete silently |

## Drift the demo must show (planted on purpose)
- A new column added to a table with no contract entry (detected, build red).
- A dashboard field that resolves to no catalogued column.
- Two dashboards defining "active customer" differently (glossary term with two implementations).
- A grant whose expiry has passed but is still present.
- A dashboard nobody opened in 90 days.
- A legacy table with no owner, under a **waiver that expires**.
