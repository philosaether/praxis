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
    user_id: int | None = None,  # deprecated, use entity_id
    inbox_only: bool = False,
    outbox_only: bool = False,
    assigned_to: int | None = None,  # Filter by assigned user
    tag_names: list[str] | None = None,  # Filter by tag names
    search_query: str | None = None,  # Search in name and notes
) -> list[Task]:
    """List tasks with optional filters. Done tasks sorted to bottom.

    For the main queue, pass both entity_id and assigned_to (user_id) to get:
    - Tasks assigned to the user (from any entity)
    - OR unassigned tasks owned by the user's entity
    - OR tasks created by the user (so they see tasks they made on shared priorities)

    tag_names: If provided, only return tasks that have at least one of these tags.
    search_query: If provided, filter to tasks where name or notes contains the query.
    """
    ensure_schema()
    with get_connection() as conn:
        # Base query - may need additional JOINs for tag filtering
        if tag_names:
            # Join with task_tags and tags to filter by tag name
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

        # If both entity_id and assigned_to provided, use combined filter for queue
        if entity_id is not None and assigned_to is not None:
            # Show tasks assigned to me OR my unassigned tasks OR tasks I created
            # (The created_by check ensures users see tasks they created on shared priorities)
            query += " AND (t.assigned_to = ? OR (t.entity_id = ? AND t.assigned_to IS NULL) OR (t.created_by = ? AND t.assigned_to IS NULL))"
            params.extend([assigned_to, entity_id, assigned_to])
        elif entity_id is not None:
            query += " AND t.entity_id = ?"
            params.append(entity_id)
        elif assigned_to is not None:
            query += " AND t.assigned_to = ?"
            params.append(assigned_to)
        elif user_id is not None:
            # Fallback to deprecated user_id filter
            query += " AND t.user_id = ?"
            params.append(user_id)

        if outbox_only:
            query += " AND t.is_in_outbox = 1"
        else:
            # Hide outbox tasks from all non-outbox views
            query += " AND (t.is_in_outbox = 0 OR t.is_in_outbox IS NULL)"

            if inbox_only:
                query += " AND t.priority_id IS NULL"
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
