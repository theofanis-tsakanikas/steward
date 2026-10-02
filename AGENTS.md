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

## Where things stand (2026-10-02)

- Closed and merged: T000–T022, T010–T017 (PRs through #41). Claims 1–7 offline; live estate applied, captured, destroyed.
- **T030 open.** Hosted demo: https://steward-governance.streamlit.app (public, no login). D7 done. Remaining unlock: **D8** — INTERVIEW 3-minute script spoken with the author. Dry-run against the URL is dated in `SESSION-LOG.md`. T031 is cut.
- **T024** blocked on a Collibra trial (D2 expiry 2026-10-05). Mock stands until then.
- Bootstrap still in the GCP project until it is deleted. DAY-ONE 4 / 7 / 8 still open (author).
- Deadline: done before **2026-10-06**. Cut order is in `KICKOFF.md`.
