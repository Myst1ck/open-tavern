# Open Tavern — SETUP / Bring-Up Playbook

Authoritative bring-up doc. Fresh machine → follow this. Generated 2026-08-28 by `/up`. Refreshed 2026-09-08 by `/up` — verified bring-up, all endpoints 200. Refreshed 2026-09-11 — auth/bind/proxy env vars, compose runtime, migration runner documented. Refreshed 2026-09-20 — SELinux `:Z` volume, uid 10001 ownership fix, token requirement under compose, frontend `Created`-state quirk. Refreshed 2026-09-20 (later) — backend host port now binds Tailscale IP (not loopback), CORS middleware order fix, podman-compose stale-image gotcha. Refreshed 2026-09-20 — start flow now world generation (textarea → Generate World → preview → Accept) before character creation. Refreshed 2026-09-21 — frontend image build chain fixed (pnpm pin, Node 22 base, workspace COPY, .dockerignore, preview CMD); both images rebuilt, endpoints 200. Refreshed 2026-09-21 (later) — start flow is now home → worldgen (**Forge your world**) → character → play; world generation moved off the home screen to a dedicated step entered via the **Create new tale** card. Refreshed 2026-09-21 (local mode) — local start documented with root `.env` sourcing (backend has no `.env` loader); uvicorn :8000 + vite :5173 verified 200. Refreshed 2026-09-21 (proxy architecture) — bearer-token auth removed from frontend; backend binds `127.0.0.1:8000` (localhost-only), Vite on `0.0.0.0:5173` proxies `/sessions` + `/world` to backend, tailnet devices reach frontend only.

## Architecture

| Layer    | Tech                              | Port | Notes                          |
|----------|-----------------------------------|------|--------------------------------|
| Backend  | Python 3.13+ / FastAPI / uvicorn  | 8000 | API + game engine + SQLite     |
| Frontend | React 19 / Vite 6 / TypeScript    | 5173 | Chat UI (vite preview, built dist) |
| Storage  | SQLite (stdlib `sqlite3`)         | —    | File `backend/open_tavern.db`  |
| AI       | OpenAI-compatible chat client     | —    | BYO key, see env vars          |

Docker/Podman available. No separate DB/cache/queue services. Two containers total.

## Services

| Service  | Access URL            | Health endpoint                | Healthy response                          |
|----------|-----------------------|--------------------------------|-------------------------------------------|
| Backend  | http://127.0.0.1:8000 | `GET /sessions` → 200          | JSON array of session summaries           |
| Backend  | http://127.0.0.1:8000/docs | `GET /docs` → 200             | Swagger UI |
| Frontend | http://<host-ip>:5173 | `GET /` → 200                  | Vite-served HTML                          |

Backend binds `127.0.0.1` by default (`OPEN_TAVERN_BIND_HOST`, loopback only); frontend dev server binds `0.0.0.0`. Reachable at `http://localhost:<port>` locally. **Proxy architecture:** the frontend Vite server proxies `/sessions` and `/world` to `http://127.0.0.1:8000`, so remote (tailnet) browsers talk to the frontend origin only — the backend is never exposed off-host and no bearer token is used. Tailnet is the trust boundary.

Note: no root `/` API route — `/` on :8000 returns 404 by design. Use `/sessions` or `/docs` for health.

## Environment Variables

### Backend (read from process env; no `.env` file loader — export or run with env)

| Variable           | Default                    | Required | Description                        |
|--------------------|----------------------------|----------|------------------------------------|
| `OPENAI_API_KEY`   | —                          | no       | OpenAI-compatible API key. Optional — app starts without it; AI calls return 503 until set (env or app config) |
| `OPENAI_BASE_URL`  | `https://api.openai.com/v1`| no       | Provider base URL. Env-only — `X-Base-URL` header removed, not honored |
| `OPENAI_MODEL`     | `gpt-4o-mini`              | no       | Model to call                      |
| `OPEN_TAVERN_DB`   | `open_tavern.db`           | no       | SQLite file path (relative to cwd) |
| `OPEN_TAVERN_TOKEN`| — (unset)                  | no       | **Deprecated / unused.** Bearer-token auth removed from the frontend; backend binds loopback and Vite proxies API calls. Leave unset. (Backend still refuses a non-localhost bind with no token — keep the bind on `127.0.0.1`.) |
| `OPEN_TAVERN_BIND_HOST` | `127.0.0.1`          | no       | uvicorn bind host. Compose sets `0.0.0.0` (container network); host port binds the machine's Tailscale IP (see Production runtime) |
| `OPEN_TAVERN_TRUST_PROXY` | — (unset)          | no       | `=1` trusts `X-Forwarded-For` for rate-limit client keys. Default off — header ignored |
| `OPEN_TAVERN_ALLOWED_ORIGINS` | `http://localhost:3000` | no       | Comma-separated CORS origins. Not needed under the proxy architecture — the browser only talks to the frontend origin (same-origin), so no cross-origin requests occur |

### Frontend (`.env` file, `frontend/.env`, copy of `frontend/.env.example`)

| Variable             | Default                    | Required | Description             |
|----------------------|----------------------------|----------|-------------------------|
| `VITE_API_BASE_URL` | `""` (same-origin)         | no       | Backend base URL. Default empty → requests go to the page origin and Vite proxies `/sessions` + `/world` to `http://127.0.0.1:8000`. Override only for non-proxied setups. Key present in `.env.example` as commented-out line |

Backend has no `.env` file — export vars or run with env. `OPENAI_API_KEY` optional — app boots without it; AI features (character generation, GM narration) fail with 503 until key set via env or app config. Note: `podman-compose` reads a root `.env` for variable interpolation (e.g. `OPEN_TAVERN_TOKEN`) — that is compose-level, not a backend loader.

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
.venv/bin/uvicorn open_tavern.api.main:app --host 127.0.0.1 --port 8000
# optional hot reload: add --reload

# frontend (terminal 2) — from frontend/
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

**No token needed.** Backend binds loopback (`127.0.0.1`) and starts without
`OPEN_TAVERN_TOKEN`. The Vite dev server proxies `/sessions` and `/world` to the
backend, so the browser only ever talks to the frontend origin. Do not bind the
backend to `0.0.0.0` — that would expose the tokenless API to the network.

### Start flow (UI)

Phases: **home → worldgen → character → play**. World generation is a dedicated
step, not part of the home screen.

1. **Home** — the home screen shows the settings panel (API key), the
   saved tales list, and a **Create new tale** card. No session exists yet.
2. **World generation** — click **Create new tale** to open the dedicated
   world-generation step, titled **Forge your world**. Describe a world in the
   textarea and click **Generate World**, or click **Surprise me** for a random
   world. The AI returns a theme + premise in a preview card. Leaving this step
   discards the generated world.
3. **Refine or accept** — **Generate Again** rerolls the world; **Accept** creates
   the session and advances to character creation.
4. **Character creation** — describe the character; the AI generates a D&D 5e
   sheet. Going back to world generation abandons the pending session and resets
   character progress.
5. **Play** — type actions; the GM narrates and the engine resolves `[CHECK:...]`
   rolls.

## Docker / Podman

> Uses Podman (not Docker). `podman-compose` required.
> ⚠️ Use `podman-compose` (Python package), NOT `podman compose` (delegates to docker-compose, broken socket). If containers fail with no clear error, check you're running the right command.
> ⚠️ podman-compose 1.5.0 may print `Build command failed` after a HEALTHCHECK OCI-format warning. Non-fatal — verify image tagged (`podman images`) before treating as failure.
> ⚠️ **Stale image:** `podman-compose up -d --build backend` may build a new image but NOT recreate the container — the running container keeps the old image. Fix: `podman rm -f <container>` then `podman-compose up -d <service>`. Verify the container's image: `podman inspect <container> --format '{{.Image}}'`.
> ⚠️ **Frontend build chain (fixed 2026-09-21, keep these invariants):** frontend image builds with pnpm, not npm. Four things must stay true or build fails:
> 1. `frontend/package.json` pins `"packageManager": "pnpm@11.22.0"` — bare `corepack enable` fetches latest pnpm (12.x), which hard-fails install with `ERR_PNPM_IGNORED_BUILDS`.
> 2. pnpm 11 requires Node ≥22.13 (`node:sqlite` builtin) — Dockerfile base MUST be `node:22-slim`, not node:20.
> 3. Dockerfile `COPY` must include `pnpm-workspace.yaml` (holds `allowBuilds: esbuild: true`); omitting it → `ERR_PNPM_IGNORED_BUILDS` again.
> 4. `frontend/.dockerignore` must exclude `node_modules`, `dist`, `*.tsbuildinfo`, `.env` — compose build context is `./frontend`, root `.dockerignore` does not apply; host `node_modules` copied in makes `pnpm build` abort (`ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`).
> ⚠️ **Frontend CMD:** `pnpm preview -- --host ...` is broken — pnpm passes `--` through to the script, vite treats it as end-of-options and binds localhost:4173 (container port 5173 dead, curl 000). Correct CMD: `pnpm exec vite preview --host 0.0.0.0 --port 5173`.

### Quick start

```bash
podman-compose up --build
```

Builds images from `backend/Dockerfile` and `frontend/Dockerfile`, starts both containers.

### Build images only

```bash
podman-compose build
```

### Run in background

```bash
podman-compose up --build -d
```

Frontend quirk: podman-compose may leave `open-tavern_frontend_1` in `Created` state (gated on backend health) even after backend healthy. Workaround:

```bash
podman start open-tavern_frontend_1
```

### Stop containers

```bash
podman-compose down
```

### View logs

```bash
podman-compose logs -f backend   # follow backend logs
podman-compose logs -f frontend  # follow frontend logs
podman-compose logs              # all services
```

### Persistent data (SQLite)

SQLite DB lives in the `backend-data` volume (`docker-compose.yml` line 13). Data survives container restarts and rebuilds.

- Volume: `backend-data` → mounted at `/data` inside backend container
- DB path inside container: `/data/open_tavern.db`
- `OPEN_TAVERN_DB` env var set to `/data/open_tavern.db` (line 10)

**SELinux (Enforcing host):** volume mount MUST be `backend-data:/data:Z`. Without `:Z`, `container_t` denied write → sqlite readonly error.

**Volume ownership:** container runs `appuser` uid 10001. If DB file owned by other uid → `sqlite3.OperationalError: attempt to write a readonly database`. Fix:

```bash
podman unshare chown -R 10001:10001 /home/omera/.local/share/containers/storage/volumes/open-tavern_backend-data/_data
```

To inspect the DB from the host:

```bash
podman volume inspect open-tavern_backend-data
# copy DB out if needed:
podman cp $(podman-compose ps -q backend):/data/open_tavern.db ./open_tavern.db
```

### Production runtime

- `docker compose up --build` (or `podman-compose up --build`) builds and starts both containers.
- Backend container binds `0.0.0.0` internally (compose sets `OPEN_TAVERN_BIND_HOST=0.0.0.0` so the frontend container reaches it over the docker network); the host port must bind loopback (`127.0.0.1:8000:8000` in `docker-compose.yml`) so the tokenless API is never exposed off-host. The frontend container proxies `/sessions` + `/world` to the backend over the docker network. ⚠️ `docker-compose.yml` currently maps `OPEN_TAVERN_BIND_IP` (default Tailscale IP) — change it to `127.0.0.1` to match this topology.
- **No token auth.** `OPEN_TAVERN_TOKEN` is unset; the frontend sends no `Authorization` header. The Settings panel `X-API-Key` field is an OpenAI-key override for LLM calls, not auth. Tailnet is the trust boundary — tailnet devices reach the frontend only.
- Runs as non-root user `appuser` (uid 10001); SQLite volume `backend-data` mounted at `/data` with `:Z` (SELinux).
- `restart: unless-stopped` on both services.
- Frontend `depends_on: backend: condition: service_healthy` — waits for backend health before starting.
- Backend `HEALTHCHECK` hits `GET /sessions` (auth-exempt) every 30s.

### Files referenced

| File | Purpose |
|------|---------|
| `backend/Dockerfile` | Python 3.13-slim, installs deps, runs uvicorn on `0.0.0.0:8000` |
| `frontend/Dockerfile` | Node 22-slim, pnpm 11.22.0 (corepack via `packageManager` pin), builds dist, serves via `vite preview` on `0.0.0.0:5173` |
| `frontend/.dockerignore` | Excludes `node_modules`, `dist`, `*.tsbuildinfo`, `.env` from frontend build context |
| `frontend/pnpm-workspace.yaml` | `allowBuilds: esbuild: true` — required inside image (Dockerfile COPY) or pnpm install fails |
| `docker-compose.yml` | Defines `backend` + `frontend` services, `backend-data` volume, port mappings |
| `.dockerignore` | Excludes `.git`, `node_modules`, `.env`, `*.md`, Dockerfiles from build context |

## Remote Access (LAN / Tailscale)

Frontend is same-origin: `frontend/src/api.ts` uses an empty base URL, so requests
go to the page origin and the Vite server proxies `/sessions` + `/world` to
`http://127.0.0.1:8000`. No `VITE_API_BASE_URL` override needed.

Required for remote access:
1. Backend MUST stay on loopback (`127.0.0.1`, the default) — it is reached only through the Vite proxy, never directly.
2. Frontend MUST bind `0.0.0.0` (`--host 0.0.0.0`).
3. Firewall open on port 5173 only (8000 stays loopback).
4. No CORS config needed — the browser only talks to the frontend origin.

Symptom: `failed to fetch` in browser on character create or any API call.
Cause: backend unreachable at `127.0.0.1:8000` (not running, wrong port) OR Vite proxy missing/misconfigured.
Verify from remote device: `curl http://<host-ip>:5173/sessions` → expect `200` (proxied).

## Health Check

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/sessions   # expect 200
curl -s -o /dev/null -w "%{http_code}\n" http://<host-ip>:5173/           # expect 200
curl -s -o /dev/null -w "%{http_code}\n" http://<host-ip>:5173/sessions   # expect 200 (proxied)
```

`<host-ip>` = LAN IP of machine (e.g. `192.168.1.213`). `localhost` works for local access.

No token auth — `GET /sessions` is open. Backend `Dockerfile` HEALTHCHECK and compose `depends_on: service_healthy` both use it.

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

## Migrations

Schema migrations live in `backend/src/open_tavern/storage/db.py` as an ordered list (`_MIGRATIONS`), each entry `(version, step)`.

- Forward-only: older DBs migrate step-by-step on open; newer DBs refused with `SchemaTooNewError` (stored `schema_version` > latest known).
- Non-destructive: steps are `CREATE TABLE IF NOT EXISTS` + idempotent `ALTER TABLE ADD COLUMN` only — no `DROP`, no data loss.
- Version tracked in `meta` table (`schema_version` key); legacy unversioned DBs get a fresh write and migrate forward.

History (2026-08-28):

- `sessions` schema migrated: `title`, `updated_at`, `state_json` added via idempotent `ALTER TABLE` in `storage/db.py`.
- Legacy rows (pre-migration) backfilled: `title = world_theme`, `updated_at = created_at`.
- Hardening added in `storage/db.py`: `list_sessions`/`session_summary` coalesce `title`/`updated_at` fallback to `world_theme`/`created_at` — prevents NULL crash on any future legacy rows.

## Firewall (remote access)

Machine runs firewalld (default public zone allows only ssh/cockpit). Remote access to 5173 blocked until port opened (8000 stays loopback, no rule needed):

```bash
sudo firewall-cmd --permanent --add-port=5173/tcp
sudo firewall-cmd --reload
```

Verify: `sudo firewall-cmd --list-ports` → `5173/tcp`.

Remote over internet (not LAN) also needs router port-forwarding to this machine's LAN IP.

## Manual Steps Remaining

1. **Set `OPENAI_API_KEY`** (and optionally `OPENAI_BASE_URL`/`OPENAI_MODEL`) in the
   backend process env. Optional — app boots without it; AI features (character
   generation, GM narration) return 503 until set. Export before starting uvicorn — app
   reads process env only (no `.env` loader).
2. No seed data required — empty DB works. 2 dev sessions present in `open_tavern.db`
   (1 `up-verify` session added during 2026-09-01 `/up` verification POST /sessions; older
   dev sessions cleaned since last refresh).
3. `frontend/.env` currently empty (no keys) — fine, frontend derives backend URL from
   browser host. `.env.example` now documents the optional `VITE_API_BASE_URL` override.
4. **Frontend auth removed (2026-09-21)** — bearer-token machinery deleted from the frontend (`getToken`/`setToken`/`adoptTokenFromQuery` gone; no `Authorization` header). Backend binds loopback and Vite proxies `/sessions` + `/world`; tailnet is the trust boundary. No token to paste.
5. **Local mode verified 2026-09-21** — uvicorn `127.0.0.1:8000` + vite `0.0.0.0:5173`; `GET /sessions` → 200, `GET /` → 200. Ports were free; no containers running.
