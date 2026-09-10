<!-- Context: navigation | Priority: critical | Version: 1.0 | Updated: 2026-09-07 -->

# Context Navigation

## Directory Structure

| Directory | Description | Priority |
|-----------|-------------|----------|
| core/ | Standards, workflows, guides | high |
| project-intelligence/ | Domain knowledge, business rules | critical |

## Quick Routes

| File | Description | Priority |
|------|-------------|----------|
| project-intelligence/navigation.md | Project-specific context index | critical |
| core/workflows/ | Workflow definitions | high |

## Context Files

### Core Workflows
- `core/workflows/batch-compression.md` — Conversation compression patterns

### Project Intelligence
- `project-intelligence/technical-domain.md` — Tech stack & patterns
- `project-intelligence/business-domain.md` — Game rules & 5e model

## Routing Rules

| Task Type | Subagent | When |
|-----------|----------|------|
| Docker / networking / CORS / env config | OpenDevopsSpecialist | Docker compose, service restart, CORS fixes, Tailscale setup, firewall, env vars |
| "failed to fetch" + Tailscale | OpenDevopsSpecialist | CORS origin mismatch, API URL resolution, docker networking |
| Frontend code / React components | CoderAgent | UI logic, components, state |
| Backend code / FastAPI | CoderAgent | API endpoints, business logic |
| Tests | TestEngineer | Unit/integration tests |
| Documentation | DocWriter | README, guides, API docs |

## Subagent Delegation Patterns

| Specialist | Delegates To | For |
|------------|--------------|-----|
| OpenDevopsSpecialist | ShellRunner | Command execution (podman, docker, systemctl) |
| CoderAgent | ShellRunner | Build/test commands, git operations |
| Any specialist | ShellRunner | When bash permissions block direct execution |

**Key**: Subagents can call `task(subagent_type="ShellRunner")` to execute commands they can't run directly.
