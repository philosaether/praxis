# CLAUDE.md

## Session Start

Read these files first:
- `~/Development/.claude/WORKFLOW.md` - How to work with Phil
- `.meta/project-status.md` - What the project is, architecture, deployment
- `.meta/decisions.md` - Architectural decisions (append-only log)
- `.meta/in-progress.md` - What's being added/removed/blocked right now
- `.meta/inbox/` - Files dropped for review
- `~/Development/persona/goals.json` - Masterpiece context (Praxis is primary)
- `logical-architecture.md` - Authoritative codebase navigation map
- `.meta/designs/praxis-at-release.md` - 1.0 vision: package boundaries, process model, auth

**During the session:** When making significant decisions, append to decisions.md. When starting/finishing work, update in-progress.md.

## Project Purpose

Praxis is a cue-based task management system that generates contextual prompts for deep work, research, and networking cycles. It pulls from queue state, calendar, and historical data to deliver the right task at the right time.

**Primary goals:**
1. Working product (open-source portfolio piece)
2. Deep understanding of agent frameworks and Python

## Architecture

See `~/Development/persona/goals.json` for full architecture decisions.

| Layer | Choice |
|-------|--------|
| Stack | Claude API + Python |
| API | FastAPI |
| CLI | Typer |
| Web | FastAPI + HTMX + Jinja (MVP+1) |
| DB | SQLite (MVP) → PostgreSQL (MVP+1) |

## Development Workflow

**Conversational coding:** Phil wants to write code himself to internalize the logic.

1. Claude generates `*-suggestions.py` files with proposed implementations
2. Phil copies to `*.py` by hand, asking questions about decisions
3. Discussion happens inline - no rushing to completion

**File convention:**
- `foo-suggestions.py` - Claude's proposed implementation
- `foo.py` - Phil's reviewed/typed version

## Repo Structure

**Two git repos in this directory:**
- `praxis/` — Main codebase (github.com/philosaether/praxis)
- `praxis/.meta/` — Working docs, gitignored from main repo (github.com/philosaether/praxis-architecture)

When committing, remember to commit both:
1. Code changes to praxis repo
2. Documentation changes (PROJECT_STATUS.md, designs/, etc.) to praxis-architecture repo

**Branch policy:** Use feature branches for multi-commit work in praxis repo. If about to commit to main, warn Phil first.

## Conventions

- Minimal dependencies, explicit over implicit
- Type hints throughout
- Docstrings on public interfaces
- Tests alongside implementation (when Phil's ready)

## Related Repos

- `~/Development/praxis-scratch/` — Archived code that might be useful later
  - `sse-infrastructure/` — Server-Sent Events implementation (archived 2026-04-03 during triggers refactor). Could be useful for real-time collaboration or notifications.
