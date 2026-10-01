# ADR 0006 — Exceptions expire

**Status:** accepted 2026-10-01 · **Doctrine:** 6

## Decision
Every waiver has an expiry no more than 90 days after its approval; on expiry the finding returns and CI
goes red. Waivers are judged against the real calendar (unlike evidence, which is judged against its own
capture time). Only `CONTRACT_MISSING` is waivable.

## Enforced by
- `core/contract.py` `Waiver`: typed dates, `expires > approved_on`, ≤ 90 days.
- `core/validate.py` `apply_waivers`: `WAIVER_EXPIRED` (the finding is back), `WAIVER_REFUSED`,
  `WAIVER_UNUSED`, `WAIVER_INVALID`.
- Today's only waiver: W-001, the legacy CRM export, until 2026-11-30.
