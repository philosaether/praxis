import random
import typer
from rich import print as rprint
from rich.table import Table

from praxis import __version__
from praxis import db
from praxis import filters
from praxis.models import Task, TaskStatus
from praxis.generators import (
    GeneratorGraph,
    GeneratorType,
    GeneratorStatus,
    Generator,
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

_graph: GeneratorGraph | None = None
def get_graph() -> GeneratorGraph:
    global _graph
    if _graph is None:
        _graph = GeneratorGraph(db.get_connection)
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


# ---------------------------------------------------------------------
# Generator Commands
# ---------------------------------------------------------------------

gen_app = typer.Typer(
    name="gen",
    help="Manage generators (goals, obligations, capacities, accomplishments, practices).",
    no_args_is_help=True,
)
app.add_typer(gen_app)

@gen_app.command(name="list")
def gen_list(
    gen_type: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by type: goal, obligation, capacity, accomplishment, practice",
    ),
    active_only: bool = typer.Option(
        False,
        "--active",
        "-a",
        help="Show only active generators.",
    ),
) -> None:
    """List all generators."""
    graph = get_graph()

    if gen_type:
        try:
            generator_type = GeneratorType(gen_type.lower())
            generators = graph.by_type(generator_type)
        except ValueError:
            rprint(f"[red]Unknown type:[/red] {gen_type}")
            rprint("Valid types: goal, obligation, capacity, accomplishment, practice")
            raise typer.Exit(1)
    else:
        generators = list(graph.nodes.values())

    if active_only:
        generators = [g for g in generators if g.status == GeneratorStatus.ACTIVE]

    if not generators:
        rprint("[yellow]No generators found.[/yellow]")
        raise typer.Exit()

    table = Table(title="Generators")
    table.add_column("ID", style="bold")
    table.add_column("Type")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Parents")

    for gen in sorted(generators, key=lambda g: (g.generator_type.value, g.id)):
        parent_ids = graph.parents.get(gen.id, set())
        parents_str = ", ".join(sorted(parent_ids)) if parent_ids else "-"

        status_color = "green" if gen.status == GeneratorStatus.ACTIVE else "dim"

        table.add_row(
            gen.id,
            gen.generator_type.value,
            gen.name,
            f"[{status_color}]{gen.status.value}[/{status_color}]",
            parents_str,
        )

    rprint(table)


@gen_app.command(name="show")
def gen_show(
    generator_id: str = typer.Argument(..., help="Generator ID to show."),
) -> None:
    """Show details for a generator."""
    graph = get_graph()
    gen = graph.get(generator_id)

    if not gen:
        rprint(f"[red]Generator not found:[/red] {generator_id}")
        raise typer.Exit(1)

    rprint()
    rprint(f"[bold]{gen.name}[/bold]")
    rprint(f"[dim]{gen.generator_type.value} · {gen.id}[/dim]")
    rprint()

    # Status
    status_color = "green" if gen.status == GeneratorStatus.ACTIVE else "yellow"
    rprint(f"Status: [{status_color}]{gen.status.value}[/{status_color}]")

    # Context
    if gen.agent_context:
        rprint(f"\n[bold]Context:[/bold]\n{gen.agent_context}")

    # Type-specific fields
    if isinstance(gen, Goal):
        if gen.success_looks_like:
            rprint(f"\n[bold]Success looks like:[/bold]\n{gen.success_looks_like}")
        if gen.obsolete_when:
            rprint(f"\n[bold]Obsolete when:[/bold]\n{gen.obsolete_when}")

    elif isinstance(gen, Obligation):
        if gen.consequence_of_neglect:
            rprint(f"\n[bold]Consequence of neglect:[/bold]\n{gen.consequence_of_neglect}")

    elif isinstance(gen, Capacity):
        rprint(f"\n[bold]Delta:[/bold] {gen.delta_description}")
        if gen.measurement_method:
            rprint(f"[bold]Measurement:[/bold] {gen.measurement_method}")
        if gen.measurement_rubric:
            rprint(f"[bold]Rubric:[/bold] {gen.measurement_rubric}")

    elif isinstance(gen, Accomplishment):
        if gen.success_criteria:
            rprint(f"\n[bold]Success criteria:[/bold]\n{gen.success_criteria}")
        if gen.progress:
            rprint(f"[bold]Progress:[/bold] {gen.progress}")
        if gen.due_date:
            rprint(f"[bold]Due:[/bold] {gen.due_date.strftime('%Y-%m-%d')}")

    elif isinstance(gen, Practice):
        if gen.rhythm_frequency:
            rprint(f"\n[bold]Rhythm:[/bold] {gen.rhythm_frequency}")
        if gen.rhythm_constraints:
            rprint(f"[bold]Constraints:[/bold] {gen.rhythm_constraints}")
        if gen.generation_prompt:
            rprint(f"[bold]Generation prompt:[/bold]\n{gen.generation_prompt}")

    # Ancestry
    parent_ids = graph.parents.get(gen.id, set())
    child_ids = graph.children.get(gen.id, set())

    if parent_ids:
        rprint(f"\n[bold]Parents:[/bold] {', '.join(sorted(parent_ids))}")
    if child_ids:
        rprint(f"[bold]Children:[/bold] {', '.join(sorted(child_ids))}")

    # Path to root
    path = graph.path_to_root(gen.id)
    if len(path) > 1:
        rprint(f"\n[dim]Path to root: {' → '.join(path)}[/dim]")

    rprint()


@gen_app.command(name="tree")
def gen_tree(
    root_id: str | None = typer.Argument(
        None,
        help="Root generator ID (omit to show all roots).",
    ),
) -> None:
    """Display generator hierarchy as a tree."""
    graph = get_graph()

    if root_id:
        root = graph.get(root_id)
        if not root:
            rprint(f"[red]Generator not found:[/red] {root_id}")
            raise typer.Exit(1)
        roots = [root]
    else:
        roots = graph.roots()

    if not roots:
        rprint("[yellow]No generators found.[/yellow]")
        raise typer.Exit()

    def print_tree(gen_id: str, prefix: str = "", is_last: bool = True):
        gen = graph.get(gen_id)
        if not gen:
            return

        connector = "└── " if is_last else "├── "
        type_badge = f"[dim][{gen.generator_type.value[:3]}][/dim]"
        status_indicator = "" if gen.status == GeneratorStatus.ACTIVE else f" [yellow]({gen.status.value})[/yellow]"

        rprint(f"{prefix}{connector}{type_badge} [bold]{gen.id}[/bold]{status_indicator}")
        rprint(f"{prefix}{'    ' if is_last else '│   '}[dim]{gen.name}[/dim]")

        children = sorted(graph.children.get(gen_id, set()))
        for i, child_id in enumerate(children):
            is_last_child = (i == len(children) - 1)
            new_prefix = prefix + ("    " if is_last else "│   ")
            print_tree(child_id, new_prefix, is_last_child)

    rprint()
    for i, root in enumerate(sorted(roots, key=lambda g: g.id)):
        if i > 0:
            rprint()  # blank line between trees
        type_badge = f"[dim][{root.generator_type.value[:3]}][/dim]"
        rprint(f"{type_badge} [bold]{root.id}[/bold]")
        rprint(f"[dim]{root.name}[/dim]")

        children = sorted(graph.children.get(root.id, set()))
        for j, child_id in enumerate(children):
            is_last = (j == len(children) - 1)
            print_tree(child_id, "", is_last)
    rprint()


@gen_app.command(name="add")
def gen_add(
    gen_type: str = typer.Argument(..., help="Type: goal, obligation, capacity, accomplishment, practice"),
    gen_id: str = typer.Argument(..., help="Unique ID for this generator"),
    name: str = typer.Argument(..., help="Human-readable name"),
    parent: str | None = typer.Option(
        None,
        "--parent",
        "-p",
        help="Parent generator ID to link to.",
    ),
    context: str | None = typer.Option(
        None,
        "--context",
        "-c",
        help="Agent context (brief description).",
    ),
) -> None:
    """Add a new generator."""
    graph = get_graph()

    # Validate type
    try:
        generator_type = GeneratorType(gen_type.lower())
    except ValueError:
        rprint(f"[red]Unknown type:[/red] {gen_type}")
        rprint("Valid types: goal, obligation, capacity, accomplishment, practice")
        raise typer.Exit(1)

    # Check for duplicate ID
    if graph.get(gen_id):
        rprint(f"[red]Generator already exists:[/red] {gen_id}")
        raise typer.Exit(1)

    # Validate parent if provided
    parent_ids = None
    if parent:
        if not graph.get(parent):
            rprint(f"[red]Parent not found:[/red] {parent}")
            raise typer.Exit(1)
        parent_ids = [parent]

    # Create the appropriate subclass
    match generator_type:
        case GeneratorType.GOAL:
            gen = Goal(id=gen_id, name=name, agent_context=context)
        case GeneratorType.OBLIGATION:
            gen = Obligation(id=gen_id, name=name, agent_context=context)
        case GeneratorType.CAPACITY:
            gen = Capacity(id=gen_id, name=name, agent_context=context)
        case GeneratorType.ACCOMPLISHMENT:
            gen = Accomplishment(id=gen_id, name=name, agent_context=context)
        case GeneratorType.PRACTICE:
            gen = Practice(id=gen_id, name=name, agent_context=context)

    graph.add(gen, parent_ids=parent_ids)

    rprint(f"[green]Created {generator_type.value}:[/green] {gen_id}")
    if parent:
        rprint(f"[dim]Linked to parent: {parent}[/dim]")


@gen_app.command(name="link")
def gen_link(
    child_id: str = typer.Argument(..., help="Child generator ID"),
    parent_id: str = typer.Argument(..., help="Parent generator ID"),
) -> None:
    """Link a child generator to a parent."""
    graph = get_graph()

    try:
        graph.link(child_id, parent_id)
        rprint(f"[green]Linked:[/green] {child_id} → {parent_id}")
    except ValueError as e:
        rprint(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@gen_app.command(name="unlink")
def gen_unlink(
    child_id: str = typer.Argument(..., help="Child generator ID"),
    parent_id: str = typer.Argument(..., help="Parent generator ID"),
) -> None:
    """Remove a parent-child link."""
    graph = get_graph()

    if child_id not in graph.nodes:
        rprint(f"[red]Generator not found:[/red] {child_id}")
        raise typer.Exit(1)
    if parent_id not in graph.nodes:
        rprint(f"[red]Generator not found:[/red] {parent_id}")
        raise typer.Exit(1)

    graph.unlink(child_id, parent_id)
    rprint(f"[green]Unlinked:[/green] {child_id} ✕ {parent_id}")


@gen_app.command(name="roots")
def gen_roots() -> None:
    """List all root generators (no parents)."""
    graph = get_graph()
    roots = graph.roots()

    if not roots:
        rprint("[yellow]No root generators found.[/yellow]")
        raise typer.Exit()

    table = Table(title="Root Generators")
    table.add_column("ID", style="bold")
    table.add_column("Type")
    table.add_column("Name")
    table.add_column("Children")

    for gen in sorted(roots, key=lambda g: (g.generator_type.value, g.id)):
        child_count = len(graph.children.get(gen.id, set()))
        table.add_row(
            gen.id,
            gen.generator_type.value,
            gen.name,
            str(child_count),
        )

    rprint(table)