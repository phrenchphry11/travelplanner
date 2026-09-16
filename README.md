# Trip Planner

Turns a rough trip idea into a day-by-day itinerary. An AI research agent
proposes lodging and activities; the user picks. Product spec in
[docs/prd.md](docs/prd.md), schema in [docs/data-model.md](docs/data-model.md).

## Layout

| Path | What | Runs as |
|---|---|---|
| `web/` | React + Vite + TypeScript, React Router, Clerk, Leaflet | Render static site |
| `backend/app/` | FastAPI API, SQLModel models, Clerk JWT auth | Render web service |
| `backend/worker/` | Research worker polling `research_jobs` | Render background worker |
| `backend/alembic/` | Migrations | `alembic upgrade head` on deploy |
| `render.yaml` | Blueprint for all four services | |

## Local development

Backend (SQLite by default, no Postgres needed):

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # add CLERK_ISSUER
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/python -m worker      # in another terminal
```

Frontend:

```bash
cd web
npm install
cp .env.example .env.local      # add VITE_CLERK_PUBLISHABLE_KEY
npm run dev                     # http://localhost:5173
```

Health: `GET /health`, `GET /health/db`. Auth-gated: `GET /me`, `GET /trips`.

## Deploying

1. Create a Clerk application. Note the publishable key and the Frontend API
   URL (used as `CLERK_ISSUER`).
2. In Render, New → Blueprint, point at this repo. It creates the database
   and three services from `render.yaml`.
3. Fill the `sync: false` env vars: `CLERK_ISSUER`, `CORS_ORIGINS` (the static
   site URL), `ANTHROPIC_API_KEY`, `VITE_CLERK_PUBLISHABLE_KEY`, `VITE_API_URL`
   (the API URL).
4. Migrations run automatically before each API deploy.

## Issues

Tracked with [beads](https://github.com/steveyegge/beads): `bd ready` shows
the next unblocked epic.
