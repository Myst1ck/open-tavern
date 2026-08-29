# Open Tavern — SETUP / Bring-Up Playbook

Authoritative bring-up doc. Fresh machine → follow this. Generated 2026-08-28 by `/up`. Refreshed 2026-08-29 by `/up` — verified bring-up, all endpoints 200.

## Architecture

| Layer    | Tech                              | Port | Notes                          |
|----------|-----------------------------------|------|--------------------------------|
| Backend  | Python 3.13+ / FastAPI / uvicorn  | 8000 | API + game engine + SQLite     |
| Frontend | React 19 / Vite 6 / TypeScript    | 5173 | Chat UI (dev server)           |
| Storage  | SQLite (stdlib `sqlite3`)         | —    | File `backend/open_tavern.db`  |
| AI       | OpenAI-compatible chat client     | —    | BYO key, see env vars          |

No Docker. No separate DB/cache/queue services. Two processes total.

## Services

| Service  | Access URL            | Health endpoint                | Healthy response                          |
|----------|-----------------------|--------------------------------|-------------------------------------------|
| Backend  | http://<host-ip>:8000 | `GET /sessions` → 200          | JSON array of session summaries           |
| Backend  | http://<host-ip>:8000/docs | `GET /docs` → 200          | Swagger UI                                |
| Frontend | http://<host-ip>:5173 | `GET /` → 200                  | Vite-served HTML                          |

Both services listen on `0.0.0.0` — reachable on any interface: `http://localhost:<port>`, LAN `http://192.168.1.213:<port>`, Tailscale `http://100.88.11.28:<port>`.

Note: no root `/` API route — `/` on :8000 returns 404 by design. Use `/sessions` or `/docs` for health.

## Environment Variables

### Backend (read from process env; no `.env` file loader — export or run with env)

| Variable           | Default                    | Required | Description                        |
|--------------------|----------------------------|----------|------------------------------------|
| `OPENAI_API_KEY`   | —                          | **yes**  | OpenAI-compatible API key          |
| `OPENAI_BASE_URL`  | `https://api.openai.com/v1`| no       | Provider base URL                  |
| `OPENAI_MODEL`     | `gpt-4o-mini`              | no       | Model to call                      |
| `OPEN_TAVERN_DB`   | `open_tavern.db`           | no       | SQLite file path (relative to cwd) |

### Frontend (`.env` file, `frontend/.env`, copy of `frontend/.env.example`)

| Variable             | Default                    | Required | Description             |
|----------------------|----------------------------|----------|-------------------------|
| `VITE_API_BASE_URL` | `http://<browser-host>:8000` | no       | Backend base URL (default: same host as page, port 8000 — no override needed for LAN/Tailscale). Key present in `.env.example` as commented-out line; leave unset for host-derived default |

Backend has no `.env` file. Missing `OPENAI_API_KEY` → app boots, all endpoints work, but AI features (character generation, GM narration) fail at call time.

## Install

Prereqs: Python 3.13+, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
# backend
cd backend
uv sync --extra dev          # creates .venv, installs fastapi/uvicorn/pytest

# frontend
cd frontend
npm install
cp .env.example .env          # only if .env missing
```

## Start

```bash
# backend (terminal 1) — from backend/
cd backend
.venv/bin/uvicorn open_tavern.api.main:app --host 0.0.0.0 --port 8000
# optional hot reload: add --reload

# frontend (terminal 2) — from frontend/
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

## Remote Access (LAN / Tailscale)

Frontend derives backend URL from the browser's own host: `http://<browser-host>:8000` (`frontend/src/api.ts`). No `VITE_API_BASE_URL` override needed — browser loads `<host-ip>:5173`, frontend calls `<host-ip>:8000` automatically.

Required for remote access:
1. Backend MUST bind `0.0.0.0` — default uvicorn is `127.0.0.1` (use `--host 0.0.0.0`).
2. Frontend MUST bind `0.0.0.0` (`--host 0.0.0.0`).
3. Firewall open on ports 8000 + 5173 (see below).

Symptom: `failed to fetch` in browser on character create or any API call.
Cause: backend unreachable at `<host-ip>:8000` — usually loopback bind (started without `--host 0.0.0.0`), wrong port, or firewall block.
Verify from remote device: `curl http://<host-ip>:8000/sessions` → expect `200`.

## Health Check

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://<host-ip>:8000/sessions   # expect 200
curl -s -o /dev/null -w "%{http_code}\n" http://<host-ip>:5173/           # expect 200
```

`<host-ip>` = LAN IP of machine (e.g. `192.168.1.213`). `localhost` works for local access.

## Verify End-to-End

1. `POST /sessions` with `{"world_theme": "fantasy"}` → 201, `session_id`.
2. `POST /sessions/{id}/character` — requires LLM call → needs `OPENAI_API_KEY`.
3. `POST /sessions/{id}/action` — game loop → needs `OPENAI_API_KEY`.
4. `GET /sessions` → list includes new session.

## Tests

```bash
cd backend
.venv/bin/python -m pytest -q    # 235 passed (2026-08-28)
```

## Migration Notes (2026-08-28)

- `sessions` schema migrated: `title`, `updated_at`, `state_json` added via idempotent `ALTER TABLE` in `storage/db.py`.
- Legacy rows (pre-migration) backfilled: `title = world_theme`, `updated_at = created_at`.
- Hardening added in `storage/db.py`: `list_sessions`/`session_summary` coalesce `title`/`updated_at` fallback to `world_theme`/`created_at` — prevents NULL crash on any future legacy rows.

## Firewall (remote access)

Machine runs firewalld (default public zone allows only ssh/cockpit). Remote access to 8000/5173 blocked until ports opened:

```bash
sudo firewall-cmd --permanent --add-port=5173/tcp --add-port=8000/tcp
sudo firewall-cmd --reload
```

Verify: `sudo firewall-cmd --list-ports` → `5173/tcp 8000/tcp`.

Remote over internet (not LAN) also needs router port-forwarding to this machine's LAN IP.

## Manual Steps Remaining

1. **Set `OPENAI_API_KEY`** (and optionally `OPENAI_BASE_URL`/`OPENAI_MODEL`) in the backend process env. Missing today → AI features unavailable. Export before starting uvicorn, or create `backend/.env` (not loaded automatically — app reads process env only).
2. No seed data required — empty DB works. 5 dev sessions present in `open_tavern.db` (1 added during 2026-08-29 `/up` verification POST /sessions).
3. `frontend/.env` currently empty (no keys) — fine, frontend derives backend URL from browser host. `.env.example` now documents the optional `VITE_API_BASE_URL` override.
