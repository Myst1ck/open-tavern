<!-- Context: project-intelligence/technical | Priority: critical | Version: 1.0 | Updated: 2026-08-28 -->

# Technical Domain

**Purpose**: Tech stack, architecture, and development patterns for Open Tavern.
**Last Updated**: 2026-09-07

## Quick Reference
**Update Triggers**: Tech stack changes | New patterns | Architecture decisions
**Audience**: Developers, AI agents

## Primary Stack
| Layer         | Technology              | Version            | Rationale                       |
| ------------- | ----------------------- | ------------------ | ------------------------------- |
| Frontend      | React                   | 19.1               | SPA UI                          |
| Build         | Vite                    | 6.3                | fast dev + plugin-react         |
| Language (FE) | TypeScript              | 5.8                | strict mode                     |
| Backend       | FastAPI                 | unpinned (uv.lock) | async REST                      |
| Language (BE) | Python                  | 3.13               | required                        |
| Database      | SQLite (stdlib sqlite3) | —                  | zero-dep MVP                    |
| Styling       | plain CSS               | —                  | single styles.css, no framework |
| Container     | Podman                  | rootless           | no sudo required                |

## Architecture
- Two processes: FastAPI backend (:8000) + Vite frontend (:5173).
- AI = GM/narrator only. Pure-Python engine owns ALL dice.
- Wire protocol: AI emits tags `[CHECK:...]` `[DAMAGE:...]` `[ITEM:+/-]` `[HP:+/-]` `[CONDITION:+/-]`; engine parses/strips/applies, feeds result back.
- Backend layout: `backend/src/open_tavern/{api, dice, character, state, protocol, story, storage}` — domain-driven, engine core isolated.

## Code Patterns
### API (backend FastAPI)
```python
# REST endpoints under /sessions
POST   /sessions                     # create session
GET    /sessions                     # list sessions
GET    /sessions/{id}                # session detail
PATCH  /sessions/{id}                # rename (title)
DELETE /sessions/{id}                # delete
POST   /sessions/{id}/character      # AI generates 5e sheet JSON
POST   /sessions/{id}/actions        # player action -> narration + state + rolls
GET    /sessions/{id}/state          # current GameState
```

### API (frontend thin client)
```ts
// frontend/src/api.ts — typed fetch wrapper, no game logic
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...settingsHeaders(loadSettings()) },
  });
  if (!response.ok) throw new ApiError(response.status, await errorDetail(response));
  return (await response.json()) as T;
}
```

### Component (React)
```tsx
interface CharacterSheetProps { character: CharacterSheet }
export default function CharacterSheetView({ character }: CharacterSheetProps) {
  return <section className="panel sheet-panel">…</section>;
}
```

## Naming Conventions
| Type          | Convention | Example                       |
| ------------- | ---------- | ----------------------------- |
| Files         | kebab-case | `character-sheet.tsx` / `db.py` |
| Components    | PascalCase | `CharacterSheetView`            |
| Functions     | camelCase  | `abilityModifier`               |
| Python / DB   | snake_case | `session_id`, `open_tavern.db`    |
| TS interfaces | PascalCase | `GameState`, `RollOutcome`        |

## Code Standards
- TypeScript strict + noUnusedLocals/Parameters + noFallthroughCasesInSwitch.
- Python: pydantic models for all request/response shapes; FastAPI typed responses.
- Engine owns dice — never trust LLM for math/state; parse tags, validate, apply.
- Backend deps unpinned in pyproject.toml; exact versions in uv.lock.
- No router/state-lib/CSS-framework — keep deps minimal.
- Tests: `uv run pytest tests/ -q`.

## Security Requirements
- `OPENAI_API_KEY` via process env only (backend); frontend uses `VITE_API_BASE_URL` (no secret in frontend).
- BYO key passed as `X-API-Key` header per-request; never persisted server-side, never in repo.
- Validate all user input (pydantic); parameterized SQLite queries.
- No root `/` route on backend (404 by design); open firewalld ports explicitly for LAN.

## 📂 Codebase References
**API client**: `frontend/src/api.ts` — typed fetch wrapper + `ApiError` + settings headers.
**Components**: `frontend/src/components/` — `CharacterSheet.tsx`, `Chat.tsx`, `SavedTalesList.tsx`, `SettingsPanel.tsx`, `StateView.tsx`.
**Backend**: `backend/src/open_tavern/{api,dice,character,state,protocol,story,storage}/`.
**Config**: `frontend/package.json`, `frontend/tsconfig*.json`, `frontend/vite.config.ts`, `backend/pyproject.toml`, `backend/uv.lock`.
**Docs**: `README.md`, `SETUP.md`.

## Related Files
- Business Domain (`business-domain.md`) — game rules, D&D 5e model, GM flow.
- Decisions Log (`decisions-log.md`) — architecture decisions.
