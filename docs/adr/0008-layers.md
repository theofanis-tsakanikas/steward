# ADR 0008 — Terraform layers

**Status:** accepted 2026-10-01

| Layer | Applied | Holds | Why separate (of the four tests) |
|---|---|---|---|
| `bootstrap` | locally, once | state bucket, Workload Identity pool + GitHub provider, deployer SA, budget alerts, APIs | CI cannot create the identity it runs as |
| `estate` | CI | datasets, tables (with policy tags in the schema from the first byte), taxonomy + policy tags, landing bucket, published parameter | lifetime of the data; blast radius (destroying it loses data) |
| `governance` | CI | data policies + Masked Readers, Fine-Grained Readers, dataset viewers/editors, row policies, retention DELETEs | changes often and independently; must never be able to drop a table |
| `marketplace` | CI | expiring grants, Analytics Hub listings, the audit sink | changes per request; consumes estate names only |

Cross-layer values go through a Parameter Manager parameter (`steward-estate`), never a remote-state read.
Policy tags live in `estate` because a table must never exist untagged, even for one apply (doctrine 1).
