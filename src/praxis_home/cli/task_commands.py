"""Task-related CLI commands."""

import random
import typer
from rich import print as rprint

from praxis_core.model import Task, TaskStatus, apply_filters
from praxis_core.persistence import (
    create_task,
    list_tasks,
    update_task_status,
    seed_database,
)


def register_task_commands(app: typer.Typer) -> None:
    """Register task commands on the main app."""

    @app.command(name="next")
    def next_task(
        priority: str | None = typer.Option(
            None,
            "--priority",
            "-p",
            help="Filter to a specific priority.",
        ),
        any_task: bool = typer.Option(
            False,
            "--any",
            "-a",
            help="Ignore filters, pick from any queued task.",
        ),
    ) -> None:
        """Get the next task to work on."""
        tasks = list_tasks(priority_id=priority, status=TaskStatus.QUEUED)

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

    @app.command()
    def add(
        name: str = typer.Argument(..., help="Task name"),
        priority: str | None = typer.Option(
            None,
            "--priority",
            "-p",
            help="Priority ID to associate with.",
        ),
        notes: str | None = typer.Option(
            None,
            "--notes",
            "-n",
            help="Additional notes.",
        ),
    ) -> None:
        """Add a new task."""
        # Import here to avoid circular import
        from praxis_home.cli.app import get_graph

        # Validate priority if provided
        if priority:
            graph = get_graph()
            if not graph.get(priority):
                rprint(f"[red]Priority not found:[/red] {priority}")
                raise typer.Exit(1)

        task = create_task(name, notes, priority_id=priority)
        rprint(f"[green]Created task #{task.id}:[/green] {name}")
        if priority:
            rprint(f"[dim]Priority: {priority}[/dim]")

    @app.command()
    def done(
        task_id: int = typer.Argument(..., help="Task ID to mark complete."),
    ) -> None:
        """Mark a task as done."""
        update_task_status(task_id, TaskStatus.DONE)
        rprint(f"[green]Task #{task_id} marked complete.[/green]")

    @app.command()
    def seed() -> None:
        """Seed the database with sample data."""
        result = seed_database()

        if result["tasks"] == 0:
            rprint("[yellow]Database already seeded.[/yellow]")
        else:
            rprint(f"[green]Created {result['tasks']} tasks.[/green]")

        rprint("\nRun [bold]praxis next[/bold] to get your first task.")


def _select_task(tasks: list) -> Task | None:
    """Select a task using filters."""
    scored = apply_filters(tasks)

    if not scored:
        return None

    top_weight = scored[0].weight
    top_tier = [scored_task for scored_task in scored if scored_task.weight == top_weight]

    selected = random.choice(top_tier)
    return selected.task


def _display_task(task: Task) -> None:
    """Display a task in the terminal."""
    rprint()
    rprint(f"[bold green]{task.name}[/bold green]")
    if task.priority_name:
        rprint(f"[dim]{task.priority_name}[/dim]")
    if task.current_subtask:
        rprint(f"[cyan]→ {task.current_subtask.title}[/cyan]")
    if task.description:
        rprint(f"\n{task.description}")
    if task.due_date:
        rprint(f"\n[yellow]Due: {task.due_date.strftime('%Y-%m-%d')}[/yellow]")
    rprint()
    rprint(f"[dim]Task #{task.id} — mark complete with: praxis done {task.id}[/dim]")
