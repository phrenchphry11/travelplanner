# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->

- Exception: agents in a `travelplanner-agents/` worktree push their branch
  and open a PR, never master (see Parallel Agents)

## Parallel Agents

`scripts/agents.sh start --ready 3` (or `start <bead-id>...`) claims beads and
launches one background Claude session per bead, each in
`../travelplanner-agents/<bead-id>` on branch `agent/<bead-id>`. `list` shows
their PRs; `clean <bead-id>` removes a finished worktree. Watch sessions with
`claude agents`.

Sessions sharing the main checkout see each other's uncommitted edits. Stage
named files only, never `git add .` or `git commit -a`.

Rules for an agent in one of those worktrees:

- **One bead, one branch.** Stay in scope; file new beads for anything else.
  Every session is the same bd user, so `--claim` does not stop two sessions
  taking one bead: only start beads whose status is `open`.
- **PRs, not master.** Render deploys from master. Run the quality gates,
  `git push -u origin agent/<bead-id>`, open a PR with `gh pr create`, and put
  the URL in the bead's notes. Leave the bead in progress until the PR merges.
- **Ports come from your slot** (`.agent-slot`, N): API `8000+N`, web
  `5173+N` (`npm run dev -- --port <port>`). Your `.env` files are already set.
- **Postgres tests use your own DB.** The suite drops all tables, so never
  point it at the shared `tp` DB. Run `createdb -h localhost -p 55432 -U
  postgres tp_agent_N` and use
  `TEST_DATABASE_URL=postgresql://postgres@localhost:55432/tp_agent_N`.
- **Migrations:** before opening a PR that adds one, `git fetch && git rebase
  origin/master`, then check `.venv/bin/alembic heads` shows one head. If two,
  set your migration's `down_revision` to the other head.
- **Shared dependencies:** `backend/.venv` is a symlink to the main checkout's
  venv. Don't install into it; if requirements change (edit `requirements.in`,
  re-run pip-compile, commit both files), say so in the PR.
  `web/node_modules` is your own copy, so `npm install` is fine.
- **Conflicts:** rebase on `origin/master` and resolve; don't merge master
  into your branch.


## Build & Test

```bash
# Backend (from backend/)
.venv/bin/pip install -r requirements-dev.txt   # locked pins; edit *.in and pip-compile, never the .txt (README)
.venv/bin/pytest -q                    # API tests, in-memory SQLite (FKs on), auth overridden
TEST_DATABASE_URL=postgresql://postgres@localhost:55432/tp .venv/bin/pytest -q  # same suite on Postgres; run before deploying DB changes
.venv/bin/alembic upgrade head         # apply migrations to DATABASE_URL
.venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/python -m worker

# Frontend (from web/)
npm install
npm run build                          # tsc + vite build; must pass before commit
npm run dev                            # http://localhost:5173
```

Local env: `backend/.env` (CLERK_ISSUER) and `web/.env.local`
(VITE_CLERK_PUBLISHABLE_KEY, VITE_API_URL). Both are gitignored.

## Architecture Overview

React + Vite frontend (`web/`) talks to a FastAPI API (`backend/app/`) with
Clerk auth. A Python worker (`backend/worker/`) polls the `research_jobs`
table. Postgres on Render, SQLite locally. Deployed via `render.yaml`.
Product spec: `docs/prd.md`. Schema: `docs/data-model.md`.

## Conventions & Patterns

- Models declare foreign keys but no ORM relationships, so SQLAlchemy does
  not order inserts or deletes by dependency. When writing related rows in
  one transaction, `session.flush()` parents before adding children (and
  delete children first, flushing per table). Postgres enforces this; tests
  run SQLite with `PRAGMA foreign_keys=ON` to catch it locally.
- Timestamps are stored as naive UTC (`app.models.utcnow()`). Never write an
  aware datetime to a column: Postgres converts it through the session timezone.
