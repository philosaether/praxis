# Praxis

Cue-based task management system that generates contextual prompts for deep work.

## What it does

Praxis pulls from your task queue, calendar, and historical data to deliver the right task at the right time. Instead of staring at a todo list, you get a single cue: "Do this now."

## Status

Early development. MVP target: April 2026.

## Architecture

- **CLI**: Typer-based interface for task management and cue generation
- **API**: FastAPI backend (MVP+1)
- **Web**: HTMX + Jinja frontend (MVP+1)
- **Intelligence**: Claude API for contextual cue generation
- **Storage**: SQLite (MVP) → PostgreSQL (MVP+1)

## Generators

Praxis uses a **unified generator model** to represent goals, obligations, and the work they generate. Generators form a directed acyclic graph (DAG)—a hierarchy where items can have multiple parents.

### Generator Types

| Type | Purpose | Example |
|------|---------|---------|
| **Goal** | Chosen pursuit | "Accomplish positive change" |
| **Obligation** | Imposed requirement | "Stay out of jail" |
| **Capacity** | Skill to develop (can atrophy) | "Technical interview performance" |
| **Accomplishment** | Threshold to reach (done when done) | "Get a day job" |
| **Practice** | Recurring activity | "Leetcode drilling" |

### CLI Commands

```bash
praxis gen tree                    # view full hierarchy
praxis gen tree positive-change    # view subtree from a root
praxis gen list --type goal        # list generators by type
praxis gen show cap-technical-interviews  # show generator details
praxis gen roots                   # list root generators

praxis gen add goal my-goal "My Goal" --parent some-parent
praxis gen link child-id parent-id
praxis gen unlink child-id parent-id
```

### Example Tree

```
positive-change
└── implement-philosophy
    ├── acquire-capacity
    │   ├── cap-moral-reasoning
    │   └── cap-systems-engineering
    └── acquire-power
        ├── gain-reputation
        │   ├── cap-systems-engineering  ← shared node (two parents)
        │   └── prac-publish
        └── gain-influence
            └── acc-day-job
```

## Filters

Praxis uses a filter system to determine which tasks to surface. Filters are stored in `~/.praxis/filters.json`.

### Filter Types

**Hard filters** exclude tasks that fail the constraint. If a task fails any matching hard filter, it won't be suggested.

**Soft filters** adjust ranking. Tasks that match get a weight boost, making them more likely to be selected.

### Standard Filter Primitives

| Type | Primitive | Description | Example |
|------|-----------|-------------|---------|
| Match | `workstream` | Tasks in a specific workstream | `{"workstream": "Networking"}` |
| Match | `user` | Tasks assigned to a user | `{"user": "phil"}` |
| Match | `all` | All tasks | `{"all": true}` |
| Constraint | `hours` | Time of day (24h) | `{"after": 9, "before": 21}` |
| Constraint | `days` | Day of week | `{"only": ["monday"]}` or `{"exclude": ["saturday", "sunday"]}` |

### Example Filter

```json
{
  "id": "networking-business-hours",
  "type": "hard",
  "match": { "workstream": "Networking" },
  "constraint": { "hours": { "after": 9, "before": 21 } }
}
```

See `filters-example.json` for a complete example configuration.

## Development

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e .

# Seed with sample teleology
python seed_teleology.py

# Run CLI
praxis --help
praxis gen tree
```

## License

MIT
