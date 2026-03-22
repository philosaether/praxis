import random
import typer
from rich import print as rprint
from rich.table import Table

from praxis import __version__
from praxis import db
from praxis import filters
from praxis.models import Task, TaskStatus

app = typer.Typer(
    name="praxis",
    help="Cue-based task management system.",
    no_args_is_help=True
)

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

# ---------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------

@app.command(name="next")
def next_task(
    stream: str | None = typer.Option(
        None,
        "--stream",
        "-s",
        help="Filter to a specific workstream.",
    ),
    any_task: bool = typer.Option(
        False,
        "--any",
        "-a",
        help="Ignore filters, pick from any queued task.",
    ),
) -> None:
    workstream_id = None
    if stream:
        ws = db.get_workstream_by_name(stream)
        if not ws:
            rprint(f"[red]Unknown workstream:[/red] {stream}")
            rprint("Run [bold]praxis streams[/bold] to see available workstreams.")
            raise typer.Exit(1)
        workstream_id = ws.id
    
    tasks = db.get_queued_tasks(workstream_id)

    if not tasks:
        rprint("[bold green]Do what you will.[/bold green]")
        raise typer.Exit()
    
    if any_task:
        task = random.choice(tasks)
    else:
        task = _select_task(tasks)
    
    if task is None:
        rprint("[yellow]Do what you will.[/yellow]")
        rprint("[dim]Or use [bold]praxis next --any[/bold] to bypass filters.[/dim]")
        raise typer.Exit()

    _display_task(task)

def _select_task(tasks: list) -> Task | None:
    scored = filters.apply_filters(tasks)

    if not scored:
        return None
    
    top_weight = scored[0].weight
    top_tier = [scored_task for scored_task in scored if scored_task.weight == top_weight]

    selected = random.choice(top_tier)
    return selected.task

def _display_task(task) -> None:
    rprint()
    rprint(f"[bold green]{task.title}[/bold green]")
    if task.workstream_name:
        rprint(f"[dim]{task.workstream_name}[/dim]")
    if task.notes:
        rprint(f"\n{task.notes}")
    if task.due_date:
        rprint(f"\n[yellow]Due: {task.due_date.strftime('%Y-%m-%d')}[/yellow]")
    rprint()
    rprint(f"[dim]Task #{task.id} — mark complete with: praxis done {task.id}[/dim]")

@app.command()
def add(
    title: str = typer.Argument(..., help="Task title"),
    stream: str = typer.Option(
        ...,
        "--stream",
        "-s",
        help="Workstream for this task.",
    ),
    notes: str | None = typer.Option(
        None,
        "--notes",
        "-n",
        help="Additional notes.",
    ),
) -> None:
    ws = db.get_workstream_by_name(stream)
    if not ws:
        rprint(f"[red]Unknown workstream:[/red] {stream}")
        rprint("Run [bold]praxis streams[/bold] to see available workstreams.")
        raise typer.Exit(1)

    task = db.create_task(ws.id, title, notes)
    rprint(f"[green]Created task #{task.id}:[/green] {title}")
    rprint(f"[dim]Workstream: {ws.name}[/dim]")

@app.command()
def done(
    task_id: int = typer.Argument(..., help="Task ID to mark complete."),
) -> None:
    db.update_task_status(task_id, TaskStatus.DONE)
    rprint(f"[green]Task #{task_id} marked complete.[/green]")

@app.command()
def streams() -> None:
    workstreams = db.list_workstreams()

    if not workstreams:
        rprint("[yellow]No workstreams found.[/yellow]")
        rprint("Run [bold]praxis seed[/bold] to populate sample data.")
        raise typer.Exit()

    table = Table(title="Workstreams")
    table.add_column("Name", style="bold")
    table.add_column("Description")

    for ws in workstreams:
        table.add_row(ws.name, ws.description or "")
    
    rprint(table)

@app.command()
def seed() -> None:
    result = db.seed_database()

    if result["workstreams"] == 0 and result["tasks"] == 0:
        rprint("[yellow]Database already seeded.[/yellow]")
    else:
        rprint(f"[green]Created {result['workstreams']} workstreams and {result['tasks']} tasks.[/green]")
  
    rprint("\nRun [bold]praxis next[/bold] to get your first task.")
