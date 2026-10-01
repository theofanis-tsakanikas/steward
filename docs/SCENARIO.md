# SCENARIO — the fictional operator

## The operator
A **fictional** European mobile and fixed-line operator, active in three countries (GR, IT, DE).
The first session picks its name: obviously fictional, checked not to be an existing operator or a
well-known sample brand. Never a real company's name, logo, colours or terms.

Its data platform is on GCP: data lands in BigQuery (EU), analysts and Looker dashboards read it,
and a business catalog (Collibra) is supposed to describe it. A new governance team must make the
estate declare itself and keep the catalog honest. Steward is that team's tooling.

## The data (synthetic, seeded, deterministic)
| Table | Grain | Interesting columns | Why it is hard |
|---|---|---|---|
| `customers` | one row per customer | `customer_id`, `full_name`, `email`, `msisdn`, `birth_date`, `address` (STRUCT), `country`, `segment`, `consent` (STRUCT) | direct identifiers; nested address; consent as data |
| `customers.contracts` | ARRAY<STRUCT> inside `customers` | `plan`, `start_date`, `end_date`, `status`, `monthly_fee` | nested one-to-many; UNNEST double-counting trap |
| `usage_events` | one row per event, partitioned by `event_date`, clustered by `msisdn`, `cell_id` | `msisdn`, `imsi`, `cell_id`, `event_type` (voice/sms/data), `volume_mb`, `duration_s` | **traffic and location data** — a stricter category (ePrivacy), not only GDPR |
| `network_events` | one row per device attach | `imei` (Luhn-valid), `imsi`, `cell_id`, `ts` | device identifiers that look like plain numbers |
| `billing` | one row per invoice | `invoice_id`, `customer_id`, `iban`, `amount`, `due_date` | financial identifiers; retention driven by tax law |
| `support_tickets` | one row per ticket | `ticket_id`, `customer_id`, `notes_free_text`, `ref_2` | **PII planted in free text and in a column named `ref_2`** — claim 1's trap |
| `legacy_crm_export` | one undocumented table | cryptic column names, no contract | scenario 161: reverse-engineering metadata from a legacy system |

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
