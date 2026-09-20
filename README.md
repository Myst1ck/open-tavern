# Open Tavern

Open-source, AI-powered text RPG in the spirit of Old Greg's Tavern. You bring
your own OpenAI-compatible API key; an AI game master narrates a D&D 5e-style
adventure while a deterministic engine owns all the dice.

**Dice-ownership model:** the AI never rolls dice. It narrates and, when an
outcome is uncertain, emits a `[CHECK:...]` tag. The engine resolves the roll,
feeds the result back, and the AI narrates the outcome.

## Architecture

| Layer    | Tech                              | Responsibility                                     |
|----------|-----------------------------------|----------------------------------------------------|
| Backend  | Python + FastAPI                  | Session/character/action endpoints, game loop      |
| Engine   | Pure Python modules               | Dice math, character sheet, state, tag protocol    |
| AI       | OpenAI-compatible chat client     | Narration + structured tags (BYO key)              |
| Storage  | SQLite (stdlib `sqlite3`)         | Sessions, characters, messages                     |
| Frontend | React + Vite (TypeScript)         | Thin chat UI, character creation, sheet display    |

```
backend/src/open_tavern/
├── api/        FastAPI routes + schemas
├── dice/       d20, advantage/disadvantage, XdY expressions, skill checks
├── character/  D&D 5e sheet: validation, normalization, derived values
├── state/      immutable GameState + pure reducers
├── protocol/   parses GM tags into typed actions
├── story/      LLM client, GM prompts, two-phase turn loop, char gen
└── storage/    SQLite persistence
```

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Node 20+

### Backend

```bash
cd backend
uv sync --extra dev
```

Set environment variables:

| Variable        | Default                     | Description                       |
|-----------------|-----------------------------|-----------------------------------|
| `OPENAI_API_KEY`  | *(optional)*              | Your OpenAI-compatible API key. Optional — AI calls fail with 503 until set |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Provider base URL. Env-only — `X-Base-URL` header not honored |
| `OPENAI_MODEL`    | `gpt-4o-mini`             | Model to call                     |
| `OPEN_TAVERN_DB`  | `open_tavern.db`          | SQLite file path (optional)       |
| `OPEN_TAVERN_TOKEN` | *(unset)*               | Bearer token for API auth. Unset + non-localhost bind → startup refused |
| `OPEN_TAVERN_BIND_HOST` | `127.0.0.1`        | uvicorn bind host                 |
| `OPEN_TAVERN_TRUST_PROXY` | *(unset)*         | `=1` trusts `X-Forwarded-For` for rate-limit client keys |

Run the backend:

```bash
uv run uvicorn open_tavern.api.main:app --reload
```

Serves on `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_BASE_URL defaults to http://localhost:8000
npm run dev
```

Open the printed URL (default `http://localhost:5173`).

## Production (Docker)

```bash
docker compose up --build
```

- Backend container binds `0.0.0.0` internally; host port binds the machine's Tailscale IP (`docker-compose.yml`) — reachable over Tailscale, not LAN. Substitute your own Tailscale IP (`tailscale ip -4`).
- Non-root user, `restart: unless-stopped`, SQLite in `backend-data` volume.
- Frontend waits on backend health (`depends_on: service_healthy`); backend `HEALTHCHECK` = `GET /sessions` (auth-exempt).
- `OPENAI_API_KEY` optional — app starts without it; AI calls return 503 until set.

## Manual play flow

1. Create a session (pick a world theme).
2. Describe your character in free text (race, concept, backstory). The AI
   generates a full D&D 5e sheet as JSON; the engine validates it and computes
   every derived value (modifiers, proficiency bonus, HP) itself.
3. Type actions. The GM narrates. When an outcome is uncertain the GM emits a
   `[CHECK:...]` tag — the engine rolls automatically and the GM narrates the
   result. Repeat.

## Tag protocol

The GM embeds these tags in narration; the engine parses them, strips them from
the prose, and applies their effects. The AI never rolls dice.

| Tag | Effect |
|-----|--------|
| `[CHECK:<ability or skill> DC<n>]` | Request a d20 roll vs a difficulty class |
| `[DAMAGE:<XdY+Z>]` | Engine rolls the dice and subtracts the total from HP |
| `[ITEM:+name]` / `[ITEM:-name]` | Add / remove an inventory item |
| `[HP:+n]` / `[HP:-n]` | Change hit points directly |
| `[CONDITION:+name]` / `[CONDITION:-name]` | Apply / clear a condition |

Example: `You swing your sword. [CHECK:strength DC15] [DAMAGE:2d6]`

## Testing

```bash
cd backend
uv run pytest tests/ -q
```

## MVP limitations

- Running game state is held in an in-memory cache and resets on server
  restart; only characters and messages persist to SQLite.
- Narration is non-streaming (full response returned at once).
- OpenAI-compatible providers only; no streaming, no multi-turn memory beyond
  the persisted message history.
