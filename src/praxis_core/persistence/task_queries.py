"""Task query builder: list_tasks with filtering, sorting, search, outbox, tagging."""

from praxis_core.model.tasks import Task, TaskStatus
from praxis_core.persistence.database import get_connection
from praxis_core.persistence.task_repo import ensure_schema, _row_to_task, _get_subtasks


def list_tasks(
    priority_id: str | None = None,
    priority_ids: list[str] | None = None,  # Batch filter: tasks under any of these priorities
    status: TaskStatus | None = None,
    include_done: bool = True,
    entity_id: str | None = None,
    inbox_only: bool = False,
    outbox_only: bool = False,
    tag_names: list[str] | None = None,  # Filter by tag names
    search_query: str | None = None,  # Search in name and notes
    org_priority_ids: list[str] | None = None,  # Org priorities whose direct tasks show in inbox
) -> list[Task]:
    """List tasks with optional filters. Done tasks sorted to bottom.

    For the main queue, pass priority_ids (computed from effective_assignee)
    to get all tasks under priorities assigned to the user.

    For inbox, pass inbox_only=True and optionally org_priority_ids to include
    tasks directly under Org-type priorities the user's groups are assigned to.
    """
    ensure_schema()
    with get_connection() as conn:
        # Base query - may need additional JOINs for tag filtering
        if tag_names:
            query = """
                SELECT DISTINCT t.*, p.name as priority_name, p.priority_type as priority_type
                FROM tasks t
                LEFT JOIN priorities p ON t.priority_id = p.id
                JOIN task_tags tt ON t.id = tt.task_id
                JOIN tags tg ON tt.tag_id = tg.id
                WHERE 1=1
            """
        else:
            query = """
                SELECT t.*, p.name as priority_name, p.priority_type as priority_type
                FROM tasks t
                LEFT JOIN priorities p ON t.priority_id = p.id
                WHERE 1=1
            """
        params = []

        if outbox_only:
            if entity_id is not None:
                query += " AND t.entity_id = ?"
                params.append(entity_id)
            query += " AND t.is_in_outbox = 1"
        else:
            # Hide outbox tasks from all non-outbox views
            query += " AND (t.is_in_outbox = 0 OR t.is_in_outbox IS NULL)"

            if inbox_only:
                if org_priority_ids:
                    # Personal inbox (owned, no priority) OR tasks directly under Org priorities (any entity)
                    org_placeholders = ", ".join("?" for _ in org_priority_ids)
                    query += f" AND ((t.entity_id = ? AND t.priority_id IS NULL) OR t.priority_id IN ({org_placeholders}))"
                    params.append(entity_id)
                    params.extend(org_priority_ids)
                else:
                    if entity_id is not None:
                        query += " AND t.entity_id = ?"
                        params.append(entity_id)
                    query += " AND t.priority_id IS NULL"
            else:
                if entity_id is not None:
                    query += " AND t.entity_id = ?"
                    params.append(entity_id)
            elif priority_ids:
                placeholders = ", ".join("?" for _ in priority_ids)
                query += f" AND t.priority_id IN ({placeholders})"
                params.extend(priority_ids)
            elif priority_id:
                query += " AND t.priority_id = ?"
                params.append(priority_id)

        if status:
            query += " AND t.status = ?"
            params.append(status.value)
        elif not include_done:
            query += " AND t.status NOT IN ('done', 'dropped')"

        # Tag filter
        if tag_names:
            placeholders = ",".join("?" * len(tag_names))
            query += f" AND tg.name IN ({placeholders})"
            params.extend(tag_names)

        # Search filter (LIKE on name and description)
        if search_query:
            search_pattern = f"%{search_query}%"
            query += " AND (t.name LIKE ? OR t.description LIKE ?)"
            params.extend([search_pattern, search_pattern])

        # Sort: active tasks first (by created_at), then done tasks
        query += """ ORDER BY
            CASE WHEN t.status = 'done' THEN 1 ELSE 0 END,
            t.created_at
        """
        rows = conn.execute(query, params).fetchall()

        tasks = []
        for row in rows:
            task = _row_to_task(row)
            task.subtasks = _get_subtasks(conn, task.id)
            tasks.append(task)

        return tasks
