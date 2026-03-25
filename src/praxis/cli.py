import random
import typer
from rich import print as rprint
from rich.table import Table

from praxis import __version__
from praxis import db
from praxis import filters
from praxis.models import Task, TaskStatus
from praxis.priorities import (
    PriorityGraph,
    PriorityType,
    PriorityStatus,
    Priority,
    Goal,
    Obligation,
    Capacity,
    Accomplishment,
    Practice,
)

app = typer.Typer(
    name="praxis",
    help="Cue-based task management system.",
    no_args_is_help=True
)

_graph: PriorityGraph | None = None
def get_graph() -> PriorityGraph:
    global _graph
    if _graph is None:
        _graph = PriorityGraph(db.get_connection)
        _graph.load()
    return _graph

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
# Top-Level Commands
# ---------------------------------------------------------------------

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
    tasks = db.list_tasks(priority_id=priority, status=TaskStatus.QUEUED)

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

def _display_task(task: Task) -> None:
    rprint()
    rprint(f"[bold green]{task.title}[/bold green]")
    if task.priority_name:
        rprint(f"[dim]{task.priority_name}[/dim]")
    if task.current_subtask:
        rprint(f"[cyan]→ {task.current_subtask.title}[/cyan]")
    if task.notes:
        rprint(f"\n{task.notes}")
    if task.due_date:
        rprint(f"\n[yellow]Due: {task.due_date.strftime('%Y-%m-%d')}[/yellow]")
    rprint()
    rprint(f"[dim]Task #{task.id} — mark complete with: praxis done {task.id}[/dim]")

@app.command()
def add(
    title: str = typer.Argument(..., help="Task title"),
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
    # Validate priority if provided
    if priority:
        graph = get_graph()
        if not graph.get(priority):
            rprint(f"[red]Priority not found:[/red] {priority}")
            raise typer.Exit(1)

    task = db.create_task(title, notes, priority_id=priority)
    rprint(f"[green]Created task #{task.id}:[/green] {title}")
    if priority:
        rprint(f"[dim]Priority: {priority}[/dim]")

@app.command()
def done(
    task_id: int = typer.Argument(..., help="Task ID to mark complete."),
) -> None:
    """Mark a task as done."""
    db.update_task_status(task_id, TaskStatus.DONE)
    rprint(f"[green]Task #{task_id} marked complete.[/green]")

@app.command()
def seed() -> None:
    """Seed the database with sample data."""
    result = db.seed_database()

    if result["tasks"] == 0:
        rprint("[yellow]Database already seeded.[/yellow]")
    else:
        rprint(f"[green]Created {result['tasks']} tasks.[/green]")

    rprint("\nRun [bold]praxis next[/bold] to get your first task.")


# ---------------------------------------------------------------------
# Priority Commands
# ---------------------------------------------------------------------

priority_app = typer.Typer(
    name="priority",
    help="Manage priorities (goals, obligations, capacities, accomplishments, practices).",
    no_args_is_help=True,
)
app.add_typer(priority_app)

@priority_app.command(name="list")
def priority_list(
    priority_type: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by type: goal, obligation, capacity, accomplishment, practice",
    ),
    active_only: bool = typer.Option(
        False,
        "--active",
        "-a",
        help="Show only active priorities.",
    ),
) -> None:
    """List all priorities."""
    graph = get_graph()

    if priority_type:
        try:
            ptype = PriorityType(priority_type.lower())
            priorities = graph.by_type(ptype)
        except ValueError:
            rprint(f"[red]Unknown type:[/red] {priority_type}")
            rprint("Valid types: goal, obligation, capacity, accomplishment, practice")
            raise typer.Exit(1)
    else:
        priorities = list(graph.nodes.values())

    if active_only:
        priorities = [p for p in priorities if p.status == PriorityStatus.ACTIVE]

    if not priorities:
        rprint("[yellow]No priorities found.[/yellow]")
        raise typer.Exit()

    table = Table(title="Priorities")
    table.add_column("ID", style="bold")
    table.add_column("Type")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Parents")

    for p in sorted(priorities, key=lambda x: (x.priority_type.value, x.id)):
        parent_ids = graph.parents.get(p.id, set())
        parents_str = ", ".join(sorted(parent_ids)) if parent_ids else "-"

        status_color = "green" if p.status == PriorityStatus.ACTIVE else "dim"

        table.add_row(
            p.id,
            p.priority_type.value,
            p.name,
            f"[{status_color}]{p.status.value}[/{status_color}]",
            parents_str,
        )

    rprint(table)


@priority_app.command(name="show")
def priority_show(
    priority_id: str = typer.Argument(..., help="Priority ID to show."),
) -> None:
    """Show details for a priority."""
    graph = get_graph()
    p = graph.get(priority_id)

    if not p:
        rprint(f"[red]Priority not found:[/red] {priority_id}")
        raise typer.Exit(1)

    rprint()
    rprint(f"[bold]{p.name}[/bold]")
    rprint(f"[dim]{p.priority_type.value} · {p.id}[/dim]")
    rprint()

    # Status
    status_color = "green" if p.status == PriorityStatus.ACTIVE else "yellow"
    rprint(f"Status: [{status_color}]{p.status.value}[/{status_color}]")

    # Context
    if p.agent_context:
        rprint(f"\n[bold]Context:[/bold]\n{p.agent_context}")

    # Type-specific fields
    if isinstance(p, Goal):
        if p.success_looks_like:
            rprint(f"\n[bold]Success looks like:[/bold]\n{p.success_looks_like}")
        if p.obsolete_when:
            rprint(f"\n[bold]Obsolete when:[/bold]\n{p.obsolete_when}")

    elif isinstance(p, Obligation):
        if p.consequence_of_neglect:
            rprint(f"\n[bold]Consequence of neglect:[/bold]\n{p.consequence_of_neglect}")

    elif isinstance(p, Capacity):
        rprint(f"\n[bold]Delta:[/bold] {p.delta_description}")
        if p.measurement_method:
            rprint(f"[bold]Measurement:[/bold] {p.measurement_method}")
        if p.measurement_rubric:
            rprint(f"[bold]Rubric:[/bold] {p.measurement_rubric}")

    elif isinstance(p, Accomplishment):
        if p.success_criteria:
            rprint(f"\n[bold]Success criteria:[/bold]\n{p.success_criteria}")
        if p.progress:
            rprint(f"[bold]Progress:[/bold] {p.progress}")
        if p.due_date:
            rprint(f"[bold]Due:[/bold] {p.due_date.strftime('%Y-%m-%d')}")

    elif isinstance(p, Practice):
        if p.rhythm_frequency:
            rprint(f"\n[bold]Rhythm:[/bold] {p.rhythm_frequency}")
        if p.rhythm_constraints:
            rprint(f"[bold]Constraints:[/bold] {p.rhythm_constraints}")
        if p.generation_prompt:
            rprint(f"[bold]Generation prompt:[/bold]\n{p.generation_prompt}")

    # Ancestry
    parent_ids = graph.parents.get(p.id, set())
    child_ids = graph.children.get(p.id, set())

    if parent_ids:
        rprint(f"\n[bold]Parents:[/bold] {', '.join(sorted(parent_ids))}")
    if child_ids:
        rprint(f"[bold]Children:[/bold] {', '.join(sorted(child_ids))}")

    # Path to root
    path = graph.path_to_root(p.id)
    if len(path) > 1:
        rprint(f"\n[dim]Path to root: {' → '.join(path)}[/dim]")

    rprint()


@priority_app.command(name="tree")
def priority_tree(
    root_id: str | None = typer.Argument(
        None,
        help="Root priority ID (omit to show all roots).",
    ),
) -> None:
    """Display priority hierarchy as a tree."""
    graph = get_graph()

    if root_id:
        root = graph.get(root_id)
        if not root:
            rprint(f"[red]Priority not found:[/red] {root_id}")
            raise typer.Exit(1)
        roots = [root]
    else:
        roots = graph.roots()

    if not roots:
        rprint("[yellow]No priorities found.[/yellow]")
        raise typer.Exit()

    def print_tree(p_id: str, prefix: str = "", is_last: bool = True):
        p = graph.get(p_id)
        if not p:
            return

        connector = "└── " if is_last else "├── "
        type_badge = f"[dim][{p.priority_type.value[:3]}][/dim]"
        status_indicator = "" if p.status == PriorityStatus.ACTIVE else f" [yellow]({p.status.value})[/yellow]"

        rprint(f"{prefix}{connector}{type_badge} [bold]{p.id}[/bold]{status_indicator}")
        rprint(f"{prefix}{'    ' if is_last else '│   '}[dim]{p.name}[/dim]")

        children = sorted(graph.children.get(p_id, set()))
        for i, child_id in enumerate(children):
            is_last_child = (i == len(children) - 1)
            new_prefix = prefix + ("    " if is_last else "│   ")
            print_tree(child_id, new_prefix, is_last_child)

    rprint()
    for i, root in enumerate(sorted(roots, key=lambda x: x.id)):
        if i > 0:
            rprint()  # blank line between trees
        type_badge = f"[dim][{root.priority_type.value[:3]}][/dim]"
        rprint(f"{type_badge} [bold]{root.id}[/bold]")
        rprint(f"[dim]{root.name}[/dim]")

        children = sorted(graph.children.get(root.id, set()))
        for j, child_id in enumerate(children):
            is_last = (j == len(children) - 1)
            print_tree(child_id, "", is_last)
    rprint()


@priority_app.command(name="add")
def priority_add(
    priority_type: str = typer.Argument(..., help="Type: goal, obligation, capacity, accomplishment, practice"),
    priority_id: str = typer.Argument(..., help="Unique ID for this priority"),
    name: str = typer.Argument(..., help="Human-readable name"),
    parent: str | None = typer.Option(
        None,
        "--parent",
        "-p",
        help="Parent priority ID to link to.",
    ),
    context: str | None = typer.Option(
        None,
        "--context",
        "-c",
        help="Agent context (brief description).",
    ),
) -> None:
    """Add a new priority."""
    graph = get_graph()

    # Validate type
    try:
        ptype = PriorityType(priority_type.lower())
    except ValueError:
        rprint(f"[red]Unknown type:[/red] {priority_type}")
        rprint("Valid types: goal, obligation, capacity, accomplishment, practice")
        raise typer.Exit(1)

    # Check for duplicate ID
    if graph.get(priority_id):
        rprint(f"[red]Priority already exists:[/red] {priority_id}")
        raise typer.Exit(1)

    # Validate parent if provided
    parent_ids = None
    if parent:
        if not graph.get(parent):
            rprint(f"[red]Parent not found:[/red] {parent}")
            raise typer.Exit(1)
        parent_ids = [parent]

    # Create the appropriate subclass
    match ptype:
        case PriorityType.GOAL:
            p = Goal(id=priority_id, name=name, agent_context=context)
        case PriorityType.OBLIGATION:
            p = Obligation(id=priority_id, name=name, agent_context=context)
        case PriorityType.CAPACITY:
            p = Capacity(id=priority_id, name=name, agent_context=context)
        case PriorityType.ACCOMPLISHMENT:
            p = Accomplishment(id=priority_id, name=name, agent_context=context)
        case PriorityType.PRACTICE:
            p = Practice(id=priority_id, name=name, agent_context=context)

    graph.add(p, parent_ids=parent_ids)

    rprint(f"[green]Created {ptype.value}:[/green] {priority_id}")
    if parent:
        rprint(f"[dim]Linked to parent: {parent}[/dim]")


@priority_app.command(name="link")
def priority_link(
    child_id: str = typer.Argument(..., help="Child priority ID"),
    parent_id: str = typer.Argument(..., help="Parent priority ID"),
) -> None:
    """Link a child priority to a parent."""
    graph = get_graph()

    try:
        graph.link(child_id, parent_id)
        rprint(f"[green]Linked:[/green] {child_id} → {parent_id}")
    except ValueError as e:
        rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@priority_app.command(name="unlink")
def priority_unlink(
    child_id: str = typer.Argument(..., help="Child priority ID"),
    parent_id: str = typer.Argument(..., help="Parent priority ID"),
) -> None:
    """Remove a parent-child link."""
    graph = get_graph()

    if child_id not in graph.nodes:
        rprint(f"[red]Priority not found:[/red] {child_id}")
        raise typer.Exit(1)
    if parent_id not in graph.nodes:
        rprint(f"[red]Priority not found:[/red] {parent_id}")
        raise typer.Exit(1)

    graph.unlink(child_id, parent_id)
    rprint(f"[green]Unlinked:[/green] {child_id} ✕ {parent_id}")


@priority_app.command(name="roots")
def priority_roots() -> None:
    """List all root priorities (no parents)."""
    graph = get_graph()
    roots = graph.roots()

    if not roots:
        rprint("[yellow]No root priorities found.[/yellow]")
        raise typer.Exit()

    table = Table(title="Root Priorities")
    table.add_column("ID", style="bold")
    table.add_column("Type")
    table.add_column("Name")
    table.add_column("Children")

    for p in sorted(roots, key=lambda x: (x.priority_type.value, x.id)):
        child_count = len(graph.children.get(p.id, set()))
        table.add_row(
            p.id,
            p.priority_type.value,
            p.name,
            str(child_count),
        )

    rprint(table)
