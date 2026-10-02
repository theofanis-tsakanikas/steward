# AGENTS.md — for any coding agent (Cursor, Codex, …) continuing this project

This project was started with Claude Code. Its rules live in `CLAUDE.md`; **they apply to you
unchanged**. Read, in order: `CLAUDE.md` → `KICKOFF.md` → `PLAN.md` → `TASKS.md` → `SESSION-LOG.md`
(last entries) → the `docs/` file a task points to.

## How to work (the author's standing instructions)
- **Autonomous build.** Do not wait for the author between tasks. One branch per task atom (name in
  `TASKS.md`), small commits with evidence, open a PR with `gh`, wait for CI green, **merge it
  yourself**, continue on the critical path.
- After every closed atom: append an entry **in Greek** to `SESSION-LOG.md` (what closed, which make
  target proves it, review findings, what is open) and set the atom's `status` in `TASKS.md`.
- `review: yes` → a **fresh-context review**: the method is in `~/.claude/skills/oversight-review/SKILL.md`
  (read it). In Cursor, do it in a **new chat tab** that has not seen the work: give it the diff and the
  task's `closes` line and ask it to attack the work; fix the findings; record them in `SESSION-LOG.md`.
- Other house rules you may read by path: `~/.claude/skills/project-architecture/SKILL.md`
  (Terraform layers, WIF, gates), `~/.claude/skills/readme-standard/SKILL.md` (for T030).
- Conversation with the author: **Greek**. Repository content: **English**.
- Tooling: `uv`, `make` (the Makefile is the contract: `make test lint evals check gate-proof preflight`),
  `gh`, `terraform`. Run them yourself; do not ask the author to run commands you can run.

## Hard stops (the only times you stop and tell the author, in Greek)
1. Before any `terraform apply` or any call that **creates or costs GCP resources** (T010 onward).
   Write and `terraform validate` all of phase 3 first.
2. A `docs/DAY-ONE.md` step only the author can do (billing, credentials, trials).
3. A doc that is wrong in a way that changes a claim.

## Where things stand (2026-10-01, when Claude Code stopped)
- Closed and merged on `main`: T000–T009 (PRs #1–#10).
- **PR #11 (T020, claim 3 — LookML lineage), branch `t020-lookml`:** review + verification pass done and
  recorded in `SESSION-LOG.md`; last commit `52a78f4`. **`make preflight` has not been run on that last
  commit** → run it, push if needed, wait for CI green, merge.
- **T021 is half-built and STASHED:** `git stash list` → `t021-wip` (on `t020-lookml`). It holds the catalog
  core, the validating mock, the REST client and the sync; `sync` / `reconcile` are not yet wired into
  the CLI. After merging #11: create branch `t021-collibra` from `main`, `git stash apply` the
  `t021-wip` stash (not `t003-wip`, which is old), finish T021.
- Then **T022** (Streamlit demo, recorded mode, fixtures) → write + `terraform validate` the Terraform for
  **T010–T016** → **hard stop** with a Greek summary: what is built, what the demo shows, estimated GCP
  cost, the exact DAY-ONE inputs needed to apply.
- **Known phase-3 issue — DECISIONS B8:** BigQuery data masking needs the project to belong to a GCP
  organization. Without one, claim 2 live shows deny / clear / row-filtered but not masked values; the
  options are in `docs/DAY-ONE.md` step 1b. Raise it in the hard-stop summary; it is the author's choice.
- Deadline: done before **2026-10-06**. Cut order is in `KICKOFF.md`.
