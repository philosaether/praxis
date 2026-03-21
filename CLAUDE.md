# CLAUDE.md

## Session Start

Read these files first:
- `~/Development/.claude/WORKFLOW.md` - How to work with Phil
- `.claude/PROJECT_STATUS.md` - Project state
- `.claude/inbox/` - Files dropped for review
- `~/Development/persona/goals.json` - Masterpiece context (Praxis is primary)

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

## Conventions

- Minimal dependencies, explicit over implicit
- Type hints throughout
- Docstrings on public interfaces
- Tests alongside implementation (when Phil's ready)
