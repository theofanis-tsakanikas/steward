# REGULATORY — posture, argued, with what still needs verifying

Every statement here names its instrument and article. **Verify each before it appears in the README
or the demo** (mark `verified: <date>` next to it). This is a reference build, not legal advice.

## GDPR (Regulation (EU) 2016/679)
- **Personal data** — Art. 4(1). MSISDN, IMSI, IMEI, email, IBAN, birth date, address, name.
- **Pseudonymisation** — Art. 4(5): data that can be re-attributed with separately kept additional information **remains personal data**. Tokenised identifiers with a held key are pseudonymised, not anonymised.
- **Anonymous data** — Recital 26: outside GDPR only if re-identification is not reasonably likely. k-anonymity over quasi-identifiers is the check the demo shows, not a legal guarantee.
- **Data minimisation / storage limitation** — Art. 5(1)(c), 5(1)(e): basis for masking by default and for retention per dataset.
- **Lawful basis** — Art. 6: each contract declares one per dataset.
- **Special categories** — Art. 9: not expected in the synthetic data; the classification exists so it can be refused.
- **Right to erasure** — Art. 17: the retention report states that BigQuery time travel / fail-safe delays physical deletion.
- **Data protection by design and by default** — Art. 25: the project's thesis.
- **Records of processing** — Art. 30: the catalog is the place such records would be linked from.
- **Security of processing** — Art. 32: names pseudonymisation and encryption explicitly.

## ePrivacy Directive (2002/58/EC) — why telco data is stricter
- **Traffic data** — Art. 6: to be erased or made anonymous when no longer needed for transmission, with exceptions (e.g. billing). `usage_events` is classified `sensitive-network`.
- **Location data other than traffic data** — Art. 9: processing only anonymised or with consent. `cell_id` with time is treated as location-revealing.
- National transpositions and telecom data-retention rules differ by country and have been shaped by CJEU case law. **Not modelled**; stated as out of scope.

## Not claimed
- Compliance of any real company. Correctness of retention periods (illustrative). Any EU AI Act obligation (no AI system decides anything here; T031 proposals are advisory).
