"""Priority-related CLI commands."""

import typer
from rich import print as rprint
from rich.table import Table

from praxis_core.model import (
    PriorityType,
    PriorityStatus,
    Value,
    Goal,
    Practice,
)


priority_app = typer.Typer(
    name="priority",
    help="Manage priorities (values, goals, practices).",
    no_args_is_help=True,
)


def _get_graph():
    """Import here to avoid circular import."""
    from praxis_core.cli.app import get_graph
    return get_graph()


@priority_app.command(name="list")
def priority_list(
    priority_type: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by type: value, goal, practice",
    ),
    active_only: bool = typer.Option(
        False,
        "--active",
        "-a",
        help="Show only active priorities.",
    ),
) -> None:
    """List all priorities."""
    graph = _get_graph()

    if priority_type:
        try:
            ptype = PriorityType(priority_type.lower())
            priorities = graph.by_type(ptype)
        except ValueError:
            rprint(f"[red]Unknown type:[/red] {priority_type}")
            rprint("Valid types: value, goal, practice")
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
    graph = _get_graph()
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
    if isinstance(p, Value):
        if p.success_looks_like:
            rprint(f"\n[bold]Success looks like:[/bold]\n{p.success_looks_like}")
        if p.obsolete_when:
            rprint(f"\n[bold]Obsolete when:[/bold]\n{p.obsolete_when}")

    elif isinstance(p, Goal):
        if p.complete_when:
            rprint(f"\n[bold]Complete when:[/bold]\n{p.complete_when}")
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
    graph = _get_graph()

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
    priority_type: str = typer.Argument(..., help="Type: value, goal, practice"),
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
    graph = _get_graph()

    # Validate type
    try:
        ptype = PriorityType(priority_type.lower())
    except ValueError:
        rprint(f"[red]Unknown type:[/red] {priority_type}")
        rprint("Valid types: value, goal, practice")
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
        case PriorityType.VALUE:
            p = Value(id=priority_id, name=name, agent_context=context)
        case PriorityType.GOAL:
            p = Goal(id=priority_id, name=name, agent_context=context)
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
    graph = _get_graph()

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
    graph = _get_graph()

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
    graph = _get_graph()
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
