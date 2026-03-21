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

## Development

```bash
# Install in development mode
pip install -e ".[dev]"

# Run CLI
praxis --help
```

## License

MIT
