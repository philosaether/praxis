"""
Praxis CLI application.

Run with: praxis --help
"""

import typer
from rich import print as rprint

from praxis_core import __version__
from praxis_core.persistence import get_connection, PriorityGraph

from praxis_core.cli.task_commands import register_task_commands
from praxis_core.cli.priority_commands import priority_app


# ---------------------------------------------------------------------
# App Setup
# ---------------------------------------------------------------------

app = typer.Typer(
    name="praxis",
    help="Cue-based task management system.",
    no_args_is_help=True
)

# Register subcommands
app.add_typer(priority_app)
register_task_commands(app)


# ---------------------------------------------------------------------
# Graph Singleton
# ---------------------------------------------------------------------

_graph: PriorityGraph | None = None


def get_graph() -> PriorityGraph:
    """Get the shared PriorityGraph instance."""
    global _graph
    if _graph is None:
        _graph = PriorityGraph(get_connection)
        _graph.load()
    return _graph


# ---------------------------------------------------------------------
# Version Callback
# ---------------------------------------------------------------------

def version_callback(value: bool) -> None:
    if value:
        rprint(f"praxis {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """Praxis: set free the soul."""
    pass
