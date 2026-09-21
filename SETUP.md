# Open Tavern — SETUP / Bring-Up Playbook

Authoritative bring-up doc. Fresh machine → follow this. Generated 2026-08-28 by `/up`. Refreshed 2026-09-08 by `/up` — verified bring-up, all endpoints 200. Refreshed 2026-09-11 — auth/bind/proxy env vars, compose runtime, migration runner documented. Refreshed 2026-09-20 — SELinux `:Z` volume, uid 10001 ownership fix, token requirement under compose, frontend `Created`-state quirk. Refreshed 2026-09-20 (later) — backend host port now binds Tailscale IP (not loopback), CORS middleware order fix, podman-compose stale-image gotcha. Refreshed 2026-09-20 — start flow now world generation (textarea → Generate World → preview → Accept) before character creation. Refreshed 2026-09-21 — frontend image build chain fixed (pnpm pin, Node 22 base, workspace COPY, .dockerignore, preview CMD); both images rebuilt, endpoints 200.

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
| Backend  | http://<host-ip>:8000 | `GET /sessions` → 200          | JSON array of session summaries           |
| Backend  | http://<host-ip>:8000/docs | `GET /docs` → 200 (401 when token set) | Swagger UI |
| Frontend | http://<host-ip>:5173 | `GET /` → 200                  | Vite-served HTML                          |

Backend binds `127.0.0.1` by default (`OPEN_TAVERN_BIND_HOST`, loopback only); frontend dev server binds `0.0.0.0`. Reachable at `http://localhost:<port>` locally, `http://<host-ip>:<port>` on LAN when bound to `0.0.0.0`. Under compose, the backend host port binds the machine's Tailscale IP (see Production runtime) — reachable over Tailscale, not LAN.

Note: no root `/` API route — `/` on :8000 returns 404 by design. Use `/sessions` or `/docs` for health.

## Environment Variables

### Backend (read from process env; no `.env` file loader — export or run with env)

| Variable           | Default                    | Required | Description                        |
|--------------------|----------------------------|----------|------------------------------------|
| `OPENAI_API_KEY`   | —                          | no       | OpenAI-compatible API key. Optional — app starts without it; AI calls return 503 until set (env or app config) |
| `OPENAI_BASE_URL`  | `https://api.openai.com/v1`| no       | Provider base URL. Env-only — `X-Base-URL` header removed, not honored |
| `OPENAI_MODEL`     | `gpt-4o-mini`              | no       | Model to call                      |
| `OPEN_TAVERN_DB`   | `open_tavern.db`           | no       | SQLite file path (relative to cwd) |
| `OPEN_TAVERN_TOKEN`| — (unset)                  | yes*     | Bearer token for API auth. Unset + localhost bind → warning; unset + non-localhost bind → startup refused. Compose sets `OPEN_TAVERN_BIND_HOST=0.0.0.0`, so compose runs REQUIRE it. Generate: `openssl rand -hex 32`, put in root `.env` (compose interpolation) |
| `OPEN_TAVERN_BIND_HOST` | `127.0.0.1`          | no       | uvicorn bind host. Compose sets `0.0.0.0` (container network); host port binds the machine's Tailscale IP (see Production runtime) |
| `OPEN_TAVERN_TRUST_PROXY` | — (unset)          | no       | `=1` trusts `X-Forwarded-For` for rate-limit client keys. Default off — header ignored |
| `OPEN_TAVERN_ALLOWED_ORIGINS` | `http://localhost:3000` | no       | Comma-separated CORS origins. Add `http://<host-ip>:5173` for LAN, or the Tailscale origin `http://<tailscale-ip>:5173` for remote browser access. Root `.env` ships `http://100.88.11.28:5173,http://brain:5173` — substitute your own Tailscale IP (`tailscale ip -4`) |

### Frontend (`.env` file, `frontend/.env`, copy of `frontend/.env.example`)

| Variable             | Default                    | Required | Description             |
|----------------------|----------------------------|----------|-------------------------|
| `VITE_API_BASE_URL` | `http://<browser-host>:8000` | no       | Backend base URL (default: same host as page, port 8000 — no override needed for LAN/Tailscale). Key present in `.env.example` as commented-out line; leave unset for host-derived default |

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
.venv/bin/uvicorn open_tavern.api.main:app --host 0.0.0.0 --port 8000
# optional hot reload: add --reload

# frontend (terminal 2) — from frontend/
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
```

### Start flow (UI)

1. **World generation** — describe a world in the textarea and click **Generate
   World**, or click **Surprise me** for a random world. The AI returns a theme +
   premise in a preview card. No session exists yet.
2. **Refine or accept** — **Generate Again** rerolls the world; **Accept** creates
   the session and advances to character creation.
3. **Character creation** — describe the character; the AI generates a D&D 5e
   sheet. Going back to world generation abandons the pending session and resets
   character progress.
4. **Play** — type actions; the GM narrates and the engine resolves `[CHECK:...]`
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
- Backend container binds `0.0.0.0` internally (compose sets `OPEN_TAVERN_BIND_HOST=0.0.0.0` so the frontend container reaches it over the docker network); host port binds the machine's Tailscale IP (`100.88.11.28:8000:8000` in `docker-compose.yml`) — reachable over Tailscale, not exposed on LAN. **Tailscale IP is machine-specific** — substitute your own (`tailscale ip -4`) in `docker-compose.yml`.
- `OPEN_TAVERN_TOKEN` REQUIRED under compose (non-localhost bind). Backend refuses start without it. Set in root `.env`. Auth is `Authorization: Bearer <OPEN_TAVERN_TOKEN>` only (`BearerTokenMiddleware` in `backend/src/open_tavern/api/main.py`). Frontend sends the Bearer header from the token stored via the Settings panel (`settings-token` input, persisted in localStorage by `setToken()` in `frontend/src/api.ts`). The Settings panel `X-API-Key` field remains an OpenAI-key override for LLM calls, not auth. Under compose (token set), paste `OPEN_TAVERN_TOKEN` into the frontend Settings panel once; UI write flows then authenticate normally.
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

Frontend derives backend URL from the browser's own host: `http://<browser-host>:8000` (`frontend/src/api.ts`). No `VITE_API_BASE_URL` override needed — browser loads `<host-ip>:5173`, frontend calls `<host-ip>:8000` automatically.

Required for remote access:
1. Backend MUST bind a reachable interface — default is `127.0.0.1` (set `OPEN_TAVERN_BIND_HOST=0.0.0.0` or pass `--host 0.0.0.0`). Under compose, the host port binds the machine's Tailscale IP (`docker-compose.yml`); substitute your own (`tailscale ip -4`).
2. Frontend MUST bind `0.0.0.0` (`--host 0.0.0.0`).
3. Firewall open on ports 8000 + 5173 (see below).
4. CORS: backend only allows `localhost:3000` by default. For remote browser access, set `OPEN_TAVERN_ALLOWED_ORIGINS` to include the origin URL, e.g. `OPEN_TAVERN_ALLOWED_ORIGINS=http://localhost:5173,http://<host-ip>:5173`. For Tailscale, include the Tailscale origin (`http://<tailscale-ip>:5173`). Without this, browser API calls fail with CORS error.

Symptom: `failed to fetch` in browser on character create or any API call.
Cause: backend unreachable at `<host-ip>:8000` (loopback bind, wrong port, firewall) OR CORS origin mismatch — browser origin not in `OPEN_TAVERN_ALLOWED_ORIGINS`.
Verify from remote device: `curl http://<host-ip>:8000/sessions` → expect `200`.

**CORS preflight / middleware order:** `BearerTokenMiddleware` is added BEFORE `CORSMiddleware` in `main.py` so CORS is outermost and answers preflight `OPTIONS` for allowed origins before auth runs. If order is reversed, preflight gets `401` and the browser reports `failed to fetch` on ALL cross-origin use — even with correct origins. Symptom `failed to fetch` cross-origin → check middleware order in `create_app()`.

## Health Check

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://<host-ip>:8000/sessions   # expect 200
curl -s -o /dev/null -w "%{http_code}\n" http://<host-ip>:5173/           # expect 200
```

`<host-ip>` = LAN IP of machine (e.g. `192.168.1.213`). `localhost` works for local access.

`GET /sessions` is auth-exempt — no `OPEN_TAVERN_TOKEN` needed. Backend `Dockerfile` HEALTHCHECK and compose `depends_on: service_healthy` both use it.

`GET /docs` returns 401 when token set — expected (auth-protected), not an outage. Use `GET /sessions` → 200 as the health check.

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

Machine runs firewalld (default public zone allows only ssh/cockpit). Remote access to 8000/5173 blocked until ports opened:

```bash
sudo firewall-cmd --permanent --add-port=5173/tcp --add-port=8000/tcp
sudo firewall-cmd --reload
```

Verify: `sudo firewall-cmd --list-ports` → `5173/tcp 8000/tcp`.

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
4. **Frontend auth (fixed 2026-09-21)** — frontend now sends `Authorization: Bearer` from the Settings panel token input (`settings-token`), stored in localStorage via `setToken()` in `frontend/src/api.ts`. Under compose, paste `OPEN_TAVERN_TOKEN` into the Settings panel once; UI write flows (create session, character, action) authenticate normally. Backend verified healthy 2026-09-21 (POST /sessions → 201 via curl with Bearer token).
