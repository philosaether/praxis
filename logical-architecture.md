# Logical Architecture

Authoritative map of the Praxis codebase. If this document says a concern lives in a file, and you find that concern elsewhere, that's a bug.

**Convention**: 500 lines max per file. One concern per file. Directory names are documentation.

**Scope**: This document is a minimal, up-to-date source of truth for navigating the codebase. Keep ephemeral information (migration plans, implementation steps, deletion checklists) in planning documents, not here.

---

## src/praxis_core/

Core business logic. No web framework dependencies except FastAPI for API layer.

### model/

Data structures. No behavior, no persistence, no imports outside this package.

```
model/
├── __init__.py          — Re-exports all model classes
├── priorities.py        — Priority, Value, Goal, Practice, Initiative, Org dataclasses and PriorityType/PriorityStatus enums
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
├── schema.py            — All CREATE TABLE statements for current schema. No migration logic.├── priority_repo.py     — Priority CRUD: save, delete, row conversion├── priority_tree.py     — PriorityTree: in-memory forest, load/save edges, traversal├── priority_sharing.py  — Priority sharing: share, unshare, get_shares, permissions├── task_repo.py         — Task CRUD: create, get, update, delete, row conversion├── task_queries.py      — Task list query builder: filtering, sorting, search, outbox├── subtask_repo.py      — Subtask CRUD: create, toggle, delete, reorder├── user_repo.py         — User CRUD and password hashing├── session_repo.py      — Session lifecycle: create, validate, delete, cleanup├── invite_repo.py       — Invitation CRUD: create, validate, accept, revoke├── friend_repo.py       — Friendship CRUD: add, remove, list, are_friends
├── friend_request_repo.py — Friend request lifecycle: send, accept, decline, cancel, notification counts
├── priority_placement_repo.py — Priority adoption: adopt, unadopt, placements, fork-on-unshare
├── rule_repo.py         — Rule CRUD
└── tag_repo.py          — Tag CRUD
```

### dsl/

Vocabulary and parsing for the automation system. Defines what conditions, effects, actions, and triggers *are* and how to read them from YAML. Rules and practices both import from here but never from each other.

```
dsl/
├── __init__.py          — Re-exports public DSL API
├── conditions.py        — ConditionType enum, Condition model, EvaluationContext, evaluate_condition orchestrator
├── condition_eval/      — Condition evaluators, split by domain│   ├── __init__.py      — Re-exports all evaluators
│   ├── time.py          — Time window, day of week evaluators
│   ├── capacity.py      — Capacity threshold evaluator
│   ├── entity.py        — Tag match, status, priority type, location evaluators
│   └── task.py          — Due date proximity, overdue, staleness, engagement recency evaluators
├── triggers.py          — Schedule, Event, Cadence, ActionTrigger models and matching logic (should_fire, next_fire_time)
├── effects.py           — Effect model, EffectTarget/EffectOperator enums, apply_effect
├── actions.py           — Action types (CreateAction, MoveAction, DeleteAction, CollateAction) and specs (TaskSpec, PrioritySpec)
├── templates.py         — TaskTemplate, PriorityTemplate, template variable expansion├── date_parsing.py      — parse_due_date, _next_weekday, relative time helpers└── practice_config.py   — PracticeAction, PracticeConfig```

### rules/

Scoring pipeline. Evaluates rule conditions against tasks → applies effects to modify importance/urgency/aptness. Rules are passive — they change numbers, never produce side effects.

```
rules/
├── __init__.py          — Re-exports evaluate_rules, parse_rules
├── engine.py            — Evaluate rule conditions against tasks, accumulate effects, compute scores
├── parser.py            — Parse YAML rule syntax to Rule objects and back
└── defaults.py          — Default system rules: due-date pressure, overdue penalties, staleness
```

### practices/

Automation pipeline. Evaluates conditions → executes actions that create/move/delete tasks. Practices are active — they produce side effects.

```
practices/
├── __init__.py               — Re-exports event handlers for use by API layer
├── engine.py                 — Evaluate conditions and expand templates into specs
├── executor.py               — Execute specs: create tasks/priorities in DB
├── events.py                 — Event dispatch: on_task_completed, on_priority_created, etc.
├── scheduler.py              — Schedule firing logic: next_fire_time, should_fire
└── parser.py                 — Parse YAML practice configs
```

### prioritization.py

Task ranking: computes (importance + urgency) x aptness scores using rules engine. Single file, ~148 lines.

### web_api/

Internal JSON API (BFF for web UI). Runs on port 8000.

```
web_api/
├── __init__.py              — Package marker
├── app.py                   — FastAPI app, lifespan, router mounting, graph cache
├── auth.py                  — FastAPI dependencies: get_current_user, require_admin (also used by agent_api for now)
├── auth_endpoints.py        — Register, login, logout, session management
├── invite_endpoints.py      — Invitation CRUD endpoints
├── friends_endpoints.py     — Friends list and removal
├── friend_request_endpoints.py — Friend requests: send, accept, decline, cancel, notifications
├── priority_endpoints.py    — Priority CRUD, tree operations, sharing, adoption (~1000 lines — split candidate)
├── task_endpoints.py        — Task CRUD, toggle, status transitions, assignment
├── rule_endpoints.py        — Rule CRUD, toggle, import/export
├── tag_endpoints.py         — Tag search, task/priority tag management
└── trigger_endpoints.py     — Practice trigger checking and event dispatch
```

### agent_api/

JSON-first API for AI agents. Mounted on web app at /agent/*. Uses web_api/auth.py for now; will move to API key auth (tracked as task under Praxis Improvements).

```
agent_api/
├── __init__.py          — Package docstring
├── priorities.py        — Priority CRUD for agents (all types incl. org), change-type endpoint
├── tasks.py             — Task CRUD for agents
├── rules.py             — Rule CRUD for agents
└── graph.py             — Priority tree queries (roots, tree, ancestors, descendants) and mutations (link, unlink, move)
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
├── rendering.py             — render_full_page helper, HTMX detection, api_client factory, tojson filter, notification counts├── routes/                 │   ├── __init__.py          — Registers all route modules on the app
│   ├── auth.py              — Login, logout, signup, invite acceptance
│   ├── pages.py             — Top-level page routes: /, /tasks, /priorities
│   ├── priorities.py        — Priority list, create, quick-add, parent options
│   ├── priority_tree.py     — Tree view, tree pane, node rendering, drag-drop move
│   ├── priority_detail.py   — Priority detail, edit, type change, properties, notes
│   ├── priority_actions.py  — Action editor, wizard, YAML conversion
│   ├── tasks.py             — Task list, create, quick-add, detail, edit, toggle, delete, assignment
│   ├── rules.py             — Rule list, create, edit, toggle, delete, import/export
│   ├── sharing.py           — Friends, friend requests, invites, user search, priority sharing/adoption
│   ├── tags.py              — Tag search, task/priority tag CRUD
│   ├── filters.py           — Priority and tag filter dropdowns
│   ├── chips.py             — Chip partial endpoints (factory pattern)
│   └── triggers.py          — Practice trigger check proxy
├── wizards/                — Scaffolding logic for multi-step user flows
│   ├── __init__.py
│   ├── action_wizard.py    — Parse action wizard form into DSL objects
│   └── rules_wizard.py      — Parse rule editor form into conditions/effects
├── config/
│   └── rule_templates.py    — RULE_TEMPLATES constant
├── helpers/
│   ├── __init__.py
│   └── action_renderer.py   — Render practice actions as human-readable chip data
├── static/
│   ├── css/
│   │   └── main.css             — Compiled output (DO NOT EDIT — generated from SCSS)
│   ├── js/
│   │   ├── chips.js             — Chip component logic (extracted from inline script)
│   │   ├── tutorial.js          — 17-step Shepherd.js onboarding tour
│   │   └── dist/                — esbuild bundled output (DO NOT EDIT — generated from js/)
│   │       ├── chips.js         — Bundled chip scripts (~23KB)
│   │       └── tutorial.js      — Bundled tutorial + Shepherd.js (~47KB)
│   ├── scss/
│   │   ├── main.scss            — Entry point: @use imports only
│   │   ├── base/
│   │   │   ├── _variables.scss  — Design tokens: $palette, $type-colors, $chip-colors, spacing, typography
│   │   │   ├── _icons.scss      — Material Symbols Outlined icon utility classes (.icon, .icon--sm, .icon--lg)
│   │   │   ├── _reset.scss      — CSS reset
│   │   │   └── _utilities.scss  — Utility classes (sr-only, text helpers)
│   │   ├── layout/
│   │   │   ├── _container.scss  — .container flex layout, pane widths
│   │   │   ├── _header.scss     — Brand, user info, environment indicators
│   │   │   ├── _filters.scss    — Search bar, filter dropdowns, add-new bar
│   │   │   ├── _mode-nav.scss   — Sidebar nav (desktop) + bottom nav (mobile)
│   │   │   ├── _fab.scss        — Floating action button
│   │   │   └── _mobile.scss     — Mobile overrides: single-pane, back button, compact header
│   │   ├── components/
│   │   │   ├── _buttons.scss    — Button styles, new-item controls
│   │   │   ├── _pills.scss      — Unified pill primitive (type/status/score/rank/shared badges)
│   │   │   ├── _forms.scss      — Input fields, selects, labels
│   │   │   ├── _tags.scss       — Tag pills and tag input
│   │   │   ├── _links.scss      — Links list, friends list, invite display
│   │   │   ├── _chips.scss      — Input chip system (all chip types)
│   │   │   └── _modals.scss     — Modal backdrop, content, forms
│   │   ├── views/
│   │   │   ├── _list.scss       — Task/priority/rule row styling
│   │   │   ├── _detail.scss     — Detail views, edit forms, property sections
│   │   │   ├── _tree.scss       — Priority tree: nodes, drag states, context menu
│   │   │   └── _login.scss      — Auth pages: login, signup, invite accept
│   │   └── features/
│   │       ├── _rules.scss      — Rule list, import, block editor, template picker
│   │       ├── _actions.scss    — Actions editor, triggers, YAML editor
│   │       ├── _action-cards.scss — Action card BEM component (view/edit modes)
│   │       ├── _wizard.scss     — Wizard modal, progress, sentence builders
│   │       └── _wizard-compact.scss — Compact wizard grid (chipset-era action picker)
│   └── images/                  — Static images
└── templates/                   — Jinja2 templates

Build: `npm run build` compiles SCSS → CSS and bundles JS via esbuild. `npm run watch` for dev.
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

