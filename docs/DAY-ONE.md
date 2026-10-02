# DAY-ONE — manual steps, done once by the author, recorded here

Nothing here is done silently by a session. Each line gets a date and who did it.

| # | Step | Why manual | Done |
|---|---|---|---|
| 1 | Create a **new GCP project** for Steward (or confirm one), link the **billing account** | billing linkage needs the author's account | 2026-10-02, author: project created inside the organization; billing account linked (a Free Trial account, B49) |
| 1b | Does the project belong to a **GCP organization**? (`gcloud projects describe <id> --format='value(parent)'`). If not: (a) create one with Cloud Identity Free over a domain the author owns, then move the project in; or (b) accept that claim 2 live shows deny / clear / row filter but not masked values (DECISIONS B8) | BigQuery data masking requires it; nothing the session can create | 2026-10-02, author: **(a)** — the author's Google Workspace domain was activated as a GCP organization; the project sits inside it. Claim 2 live can show masked values (B8, B49) |
| 2 | Note the **project id** and **billing account id** in the session (not in the repo if private data) | inputs to bootstrap | 2026-10-02, author: filled into the git-ignored `infra/bootstrap/terraform.tfvars` — the ids stay out of the repository (P1) |
| 3 | `gcloud auth application-default login` for the **bootstrap** apply only; copy `infra/bootstrap/terraform.tfvars.example` to `terraform.tfvars` (git-ignored) and fill it in (the `gh api` line in it gives the four GitHub values) | bootstrap is local by rule | 2026-10-02, author: ADC and gcloud are the organization's super-admin account, project set; apply authorised 2026-10-02 |
| 4 | Confirm budget alerts (€30 / €50) arrive by email after bootstrap | trust the alarm before spending | |
| 5 | P1 = private now, public later · P2 = `EU` | author's decision | 2026-10-01, author; **P1 public 2026-10-02** (pre-publish pass, history rewrite, `gh repo edit --visibility public`) |
| 6 | Create the GitHub repository; allow the WIF provider for it | repo ownership | repo: 2026-10-01, session (private, B3); WIF: T010 |
| 6b | In the GitHub repository: create the **environments `deploy` and `destroy`**, with **deployment branches limited to `main`** (a **required reviewer** is the intended second gate but a private repository on the Free plan does not offer one: B34). Set the **repository variables** the bootstrap prints (`terraform output github_repository_variables`): `GCP_PROJECT_ID`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOYER_SERVICE_ACCOUNT`, `GCP_DESTROYER_SERVICE_ACCOUNT` | The federation trust pins the repository, the `main` branch and the environment name; **who may run a job in an environment is a GitHub setting, not Terraform** (DECISIONS B34) | 2026-10-02, author: environments `deploy` and `destroy` exist, deployment branches limited to `main`, **no required reviewer** (a private repository on the Free plan does not offer one — B34). Repository variables set by the session from the bootstrap outputs |
| 7 | **Request a Collibra trial** (collibra.com → Explore / Request a demo); record date and outcome | sales process, no API | |
| 8 | Check for a **Looker trial** on Google Cloud; record outcome | licence | |
| 9 | Create a **Streamlit Community Cloud** account linked to GitHub (for the hosted recorded demo) | third-party sign-up | 2026-10-02, author: account `theofanis-tsakanikas`, linked to GitHub |
| 10 | After T017: confirm in the console that the project is empty; record final spend | the destroy must be seen | 2026-10-02, session: four Terraform layers destroyed; sweep 0 leftovers. Bootstrap remains until the project is deleted. BigQuery billed ~80 MiB over 73 jobs; no €30/€50 budget notification. **2026-10-02, author: confirmed in the console that the estate is gone.** |

## Free Trial billing account (recorded 2026-10-02)

The billing account is a **Free Trial** account: EUR, 90 days, a welcome credit of about EUR 264 (read from the
console by the author, not from an API). Consequences, each argued in DECISIONS B49:
- the credit pays for usage, so **net** spend is zero until the credit is gone: the budget measures gross usage;
- a Free Trial account is *non-billable*: when the credit or the 90 days run out, billing is disabled and the
  resources stop — a hard ceiling no budget can raise, and the end date to plan around (write the signup date here:
  ____ ; the estate must be captured and destroyed before it);
- no Cloud Marketplace and no quota increases while the account is a trial (none are used);
- upgrading the account ends the trial and makes the spend real: do not, during this project.
