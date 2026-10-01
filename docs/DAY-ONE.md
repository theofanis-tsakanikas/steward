# DAY-ONE — manual steps, done once by the author, recorded here

Nothing here is done silently by a session. Each line gets a date and who did it.

| # | Step | Why manual | Done |
|---|---|---|---|
| 1 | Create a **new GCP project** for Steward (or confirm one), link the **billing account** | billing linkage needs the author's account | |
| 1b | Does the project belong to a **GCP organization**? (`gcloud projects describe <id> --format='value(parent)'`). If not: (a) create one with Cloud Identity Free over a domain the author owns, then move the project in; or (b) accept that claim 2 live shows deny / clear / row filter but not masked values (DECISIONS B8) | BigQuery data masking requires it; nothing the session can create | |
| 2 | Note the **project id** and **billing account id** in the session (not in the repo if private data) | inputs to bootstrap | |
| 3 | `gcloud auth application-default login` for the **bootstrap** apply only | bootstrap is local by rule | |
| 4 | Confirm budget alerts (€30 / €50) arrive by email after bootstrap | trust the alarm before spending | |
| 5 | P1 = private now, public later · P2 = `EU` | author's decision | 2026-10-01, author |
| 6 | Create the GitHub repository; allow the WIF provider for it | repo ownership | repo: 2026-10-01, session (private, B3); WIF: T010 |
| 7 | **Request a Collibra trial** (collibra.com → Explore / Request a demo); record date and outcome | sales process, no API | |
| 8 | Check for a **Looker trial** on Google Cloud; record outcome | licence | |
| 9 | Create a **Streamlit Community Cloud** account linked to GitHub (for the hosted recorded demo) | third-party sign-up | |
| 10 | After T017: confirm in the console that the project is empty; record final spend | the destroy must be seen | |
