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

## Filters

Praxis uses a filter system to determine which tasks to surface. Filters are stored in `~/.praxis/filters.json`.

### Filter Types

**Hard filters** exclude tasks that fail the constraint. If a task fails any matching hard filter, it won't be suggested.

**Soft filters** adjust ranking. Tasks that match get a weight boost, making them more likely to be selected.

### Standard Filter Primitives

These are the building blocks for all filters:

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

```json
{
  "id": "leetcode-morning-boost",
  "type": "soft",
  "match": { "workstream": "Leetcode" },
  "weight": { "boost": 20, "when": { "hours": { "before": 12 } } }
}
```

See `src/praxis/filters-example.json` for a complete example configuration.

## Development

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e .

# Run CLI
praxis --help
```

## License

MIT
