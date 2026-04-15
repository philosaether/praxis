# Logical Architecture

Authoritative map of the Praxis codebase. If this document says a concern lives in a file, and you find that concern elsewhere, that's a bug.

**Convention**: 500 lines max per file. One concern per file. Directory names are documentation.

---

## src/praxis_core/

Core business logic. No web framework dependencies except FastAPI for API layer.

### model/

Data structures. No behavior, no persistence, no imports outside this package.

```
model/
├── __init__.py          — Re-exports all model classes
├── priorities.py        — Priority, Value, Goal, Practice, Initiative dataclasses and PriorityType/PriorityStatus enums
├── tasks.py             — Task, Subtask dataclasses and TaskStatus enum
├── users.py             — User, Session dataclasses and UserRole enum
├── entities.py          — Entity dataclass for multi-tenancy
├── rules.py             — Rule, RuleCondition, RuleEffect dataclasses
├── filters.py           — ScoredTask wrapper and filter matching logic
└── tags.py              — Tag dataclass
```

### persistence/

Database access. Each file owns one table (or table group). No business logic beyond CRUD.

Schema management uses a two-layer pattern:
- **schema.py** — Single source of truth for current table definitions (`CREATE TABLE IF NOT EXISTS`). Stable; only changes when the schema itself evolves. Runs on every startup to handle fresh installs.
- **migrations/** — Numbered, append-only scripts for transforming existing data. Each runs exactly once, tracked by a `schema_version` table. Startup path: `ensure_schema()` → `run_migrations()`.

```
persistence/
├── __init__.py          — Re-exports connection utilities and CRUD functions
├── database.py          — SQLite connection factory, path resolution, pragmas
├── schema.py            — All CREATE TABLE statements for current schema. No migration logic. (NEW — extracted from scattered schema blocks)
├── priority_repo.py     — Priority CRUD: save, delete, row conversion (NEW — extracted from priority_persistence.py)
├── priority_tree.py     — PriorityTree: in-memory forest, load/save edges, traversal (NEW — extracted from priority_persistence.py)
├── priority_sharing.py  — Priority sharing: share, unshare, get_shares, permissions (NEW — extracted from priority_persistence.py)
├── task_repo.py         — Task CRUD: create, get, update, delete, row conversion (NEW — renamed from task_persistence.py)
├── task_queries.py      — Task list query builder: filtering, sorting, search, outbox (NEW — extracted from task_persistence.py)
├── subtask_repo.py      — Subtask CRUD: create, toggle, delete, reorder (NEW — extracted from task_persistence.py)
├── user_repo.py         — User CRUD and password hashing (NEW — extracted from user_persistence.py)
├── session_repo.py      — Session lifecycle: create, validate, delete, cleanup (NEW — extracted from user_persistence.py)
├── invite_repo.py       — Invitation CRUD: create, validate, accept, revoke (NEW — extracted from user_persistence.py)
├── friend_repo.py       — Friendship CRUD: add, remove, list, are_friends (NEW — extracted from user_persistence.py)
├── rule_repo.py         — Rule CRUD (renamed from rule_persistence.py)
└── tag_repo.py          — Tag CRUD (renamed from tag_persistence.py)
```

### dsl/

Vocabulary and parsing for the automation system. Defines what conditions, effects, actions, and triggers *are* and how to read them from YAML. Rules and practices both import from here but never from each other.

```
dsl/
├── __init__.py          — Re-exports public DSL API
├── conditions.py        — ConditionType enum, Condition model, EvaluationContext, evaluate_condition orchestrator
├── condition_eval/      — Condition evaluators, split by domain (NEW — extracted from conditions.py)
│   ├── __init__.py      — Re-exports all evaluators
│   ├── time.py          — Time window, day of week evaluators
│   ├── capacity.py      — Capacity threshold evaluator
│   ├── entity.py        — Tag match, status, priority type, location evaluators
│   └── task.py          — Due date proximity, overdue, staleness, engagement recency evaluators
├── triggers.py          — Schedule, Event, Cadence, ActionTrigger models and matching logic (should_fire, next_fire_time)
├── effects.py           — Effect model, EffectTarget/EffectOperator enums, apply_effect
├── actions.py           — Action types (CreateAction, MoveAction, DeleteAction, CollateAction) and specs (TaskSpec, PrioritySpec)
├── templates.py         — TaskTemplate, PriorityTemplate, template variable expansion (NEW — extracted from actions.py)
├── date_parsing.py      — parse_due_date, _next_weekday, relative time helpers (NEW — extracted from actions.py)
└── practice_config.py   — PracticeAction, PracticeConfig (NEW — single source of truth, consolidates dsl/actions.py + triggers/models_v2.py)
```

### rules/

Scoring pipeline. Evaluates rule conditions against tasks → applies effects to modify importance/urgency/aptness. Rules are passive — they change numbers, never produce side effects.

```
rules/
├── __init__.py          — Re-exports evaluate_rules, parse_rules
├── engine.py            — Evaluate rule conditions against tasks, accumulate effects, compute scores
├── parser.py            — Parse YAML rule syntax to Rule objects and back (renamed from dsl.py)
└── defaults.py          — Default system rules: due-date pressure, overdue penalties, staleness
```

### practices/

Automation pipeline. Evaluates conditions → executes actions that create/move/delete tasks. Practices are active — they produce side effects.

```
practices/                    (NEW — replaces triggers/)
├── __init__.py               — Re-exports event handlers for use by API layer
├── engine.py                 — Evaluate conditions and expand templates into specs (from triggers/engine_v2.py)
├── executor.py               — Execute specs: create tasks/priorities in DB (from triggers/executor_v2.py)
├── events.py                 — Event dispatch: on_task_completed, on_priority_created, etc. (from triggers/events.py)
├── scheduler.py              — Schedule firing logic: next_fire_time, should_fire (from triggers/schedule_v2.py)
└── parser.py                 — Parse YAML practice configs (from triggers/dsl_v2.py)
```

### prioritization.py

Task ranking: computes (importance + urgency) x aptness scores using rules engine. Single file, ~148 lines.

### web_api/

Internal JSON API (BFF for web UI). Runs on port 8000. Renamed from `api/` — no API is the default.

```
web_api/                          (renamed from api/)
├── __init__.py              — Package marker
├── app.py                   — FastAPI app, lifespan, router mounting, graph cache
├── auth.py                  — FastAPI dependencies: get_current_user, require_admin (also used by agent_api for now)
├── auth_endpoints.py        — Register, login, logout, session management
├── invite_endpoints.py      — Invitation CRUD endpoints
├── friends_endpoints.py     — Friends list and permission checking
├── priority_endpoints.py    — Priority CRUD, tree operations, sharing (stays ~880 lines for now — split if it grows)
├── task_endpoints.py        — Task CRUD, toggle, status transitions
├── rule_endpoints.py        — Rule CRUD, toggle, import/export
├── tag_endpoints.py         — Tag search, task/priority tag management
└── trigger_endpoints.py     — Practice trigger checking and event dispatch
```

### agent_api/

JSON-first API for AI agents. Mounted on web app at /agent/*. Uses web_api/auth.py for now; will move to API key auth (tracked as task under Praxis Improvements).

```
agent_api/
├── __init__.py          — Package docstring
├── priorities.py        — Priority CRUD for agents
├── tasks.py             — Task CRUD for agents
├── rules.py             — Rule CRUD for agents
└── graph.py             — Priority tree queries (roots, tree, ancestors, descendants)
```

### migrations/

Numbered, append-only migration scripts. Each runs exactly once, tracked by a `schema_version` table. Startup path: `schema.py` creates tables if fresh → `run_migrations()` applies any new scripts.

```
migrations/
├── __init__.py                    — run_migrations(): check version table, apply new scripts in order
├── 001_priorities_cleanup.py      — Drop obsolete columns, rename fields
├── 002_notes_to_description.py    — Rename notes→description on priorities and tasks tables
└── 003_add_practice_columns.py    — Add actions_config, last_triggered_at, etc.
```

---

## src/praxis_web/

Web UI server. FastAPI + HTMX + Jinja2. Runs on port 8080, proxies to core API.

```
praxis_web/
├── app.py                   — FastAPI app setup, agent API mounting, startup diagnostics, config (~100 lines)
├── rendering.py             — render_full_page helper, HTMX detection, api_client factory (NEW — extracted from app.py)
├── routes/                  (NEW — extracted from app.py)
│   ├── __init__.py          — Registers all route modules on the app
│   ├── auth.py              — Login, logout, signup, invite acceptance (~193 lines from app.py)
│   ├── pages.py             — Top-level page routes: /, /tasks, /priorities (~89 lines from app.py)
│   ├── priorities.py        — Priority list, create, quick-add, parent options (~152 lines from app.py)
│   ├── priority_tree.py     — Tree view, tree pane, node rendering, drag-drop move (~110 lines from app.py)
│   ├── priority_detail.py   — Priority detail, edit, type change, properties, notes (~207 lines from app.py)
│   ├── priority_actions.py  — Action editor, wizard, YAML conversion (~300 lines from app.py — logic extracted to wizards/)
│   ├── tasks.py             — Task list, create, quick-add, detail, edit, toggle, delete (~297 lines from app.py)
│   ├── rules.py             — Rule list, create, edit, toggle, delete, import/export (~300 lines from app.py — logic extracted to wizards/)
│   ├── sharing.py           — Friends, invites, user search, priority sharing (~120 lines from app.py)
│   ├── tags.py              — Tag search, task/priority tag CRUD (~115 lines from app.py)
│   ├── filters.py           — Priority and tag filter dropdowns (~32 lines from app.py)
│   ├── chips.py             — Chip partial endpoints, refactored to factory pattern (~80 lines from app.py, down from 280)
│   └── triggers.py          — Practice trigger check proxy (~13 lines from app.py)
├── wizards/                (NEW — scaffolding logic for multi-step user flows)
│   ├── __init__.py
│   ├── action_wizard.py    — Parse action wizard form into DSL objects (~180 lines from app.py lines 1395-1576)
│   └── rules_wizard.py      — Parse rule editor form into conditions/effects (~110 lines from app.py lines 2746-2858)
├── config/                  (NEW)
│   └── rule_templates.py    — RULE_TEMPLATES constant (~68 lines from app.py)
├── helpers/
│   ├── __init__.py
│   └── action_renderer.py   — Render practice actions as human-readable chip data
├── static/                  — CSS, SCSS, images (unchanged)
└── templates/               — Jinja2 templates (unchanged)
```

---

## src/praxis_home/

Open-source home server package. Thin wrapper around core. Also home to the Typer CLI.

```
praxis_home/
├── __init__.py          — Package marker and version
├── config.py            — Configuration management
├── server.py            — Entry point: setup, migration, start commands
└── cli/                 (moved from praxis_core/cli/)
    ├── __init__.py      — Exports CLI app
    ├── app.py           — Typer app setup and command registration
    ├── priority_commands.py — List, show, create, link priorities
    └── task_commands.py     — List, next, add, complete tasks
```

Note: `pyproject.toml` entry point changes from `praxis_core.cli:app` to `praxis_home.cli:app`.

---

## Deletion Plan

These files are removed during the refactor (code consolidated elsewhere):

| File | Replaced by |
|------|-------------|
| `triggers/models_v2.py` | `dsl/practice_config.py` + existing `dsl/` models |
| `triggers/engine_v2.py` | `practices/engine.py` |
| `triggers/executor_v2.py` | `practices/executor.py` |
| `triggers/events.py` | `practices/events.py` |
| `triggers/schedule_v2.py` | `practices/scheduler.py` |
| `triggers/dsl_v2.py` | `practices/parser.py` |
| `triggers/__init__.py` | `practices/__init__.py` |
| `persistence/priority_persistence.py` | `persistence/priority_repo.py` + `priority_tree.py` + `priority_sharing.py` |
| `persistence/task_persistence.py` | `persistence/task_repo.py` + `task_queries.py` + `subtask_repo.py` |
| `persistence/user_persistence.py` | `persistence/user_repo.py` + `session_repo.py` + `invite_repo.py` + `friend_repo.py` |
| `rules/dsl.py` | `rules/parser.py` |
| `praxis_core/cli/` | `praxis_home/cli/` |

---

## Migration Order

Execute in this order to minimize broken imports at any step:

1. **api/ → web_api/** — Rename directory, update all imports. Mechanical, touches many files but low risk.
2. **dsl/ consolidation** — Extract `templates.py`, `date_parsing.py`, `practice_config.py` from `actions.py`. Extract `condition_eval/` from `conditions.py`. Delete `triggers/models_v2.py`.
3. **triggers/ → practices/** — Rename directory, update imports. No logic changes.
4. **rules/dsl.py → rules/parser.py** — Rename only.
5. **persistence/ restructure** — Extract `schema.py` and migration runner. Split each large file. Update `__init__.py` re-exports.
6. **cli/ → praxis_home/cli/** — Move directory, update pyproject.toml entry point.
7. **praxis_web/app.py decomposition** — Extract routes, services, config. Biggest move but no core dependencies.
8. **Verify & clean** — Run app locally, fix any remaining import issues, delete old files.
