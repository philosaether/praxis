"""
Praxis Web UI server.

Run with: uvicorn praxis_web.app:app --port 8080
"""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from praxis_web.rendering import PRAXIS_ENV

# -----------------------------------------------------------------------------
# App Setup
# -----------------------------------------------------------------------------

_log = logging.getLogger("praxis.web")

app = FastAPI(title="Praxis Web")

# Static files
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# -----------------------------------------------------------------------------
# Startup: ensure schemas
# -----------------------------------------------------------------------------

@app.on_event("startup")
async def _startup():
    """Ensure all DB tables exist and log diagnostics."""
    from praxis_core.persistence import ensure_all_schemas, ensure_default_rules, get_connection
    ensure_all_schemas()
    ensure_default_rules()

    # Auto-migrate (same logic as web_api/app.py lifespan)
    conn = get_connection()

    # tutorial_completed on users
    user_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "tutorial_completed" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN tutorial_completed INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE users SET tutorial_completed = 1")
        conn.commit()
        _log.warning("Auto-migrated: added tutorial_completed to users")

    # Priority-level assignment
    p_cols = {row[1] for row in conn.execute("PRAGMA table_info(priorities)").fetchall()}
    if "assigned_to_entity_id" not in p_cols:
        conn.execute("ALTER TABLE priorities ADD COLUMN assigned_to_entity_id TEXT REFERENCES entities(id)")
        conn.execute("UPDATE priorities SET assigned_to_entity_id = entity_id WHERE entity_id IS NOT NULL")
        conn.commit()
        _log.warning("Auto-migrated: added assigned_to_entity_id to priorities")
    for col in ("auto_assign_owner", "auto_assign_creator"):
        if col in p_cols:
            try:
                conn.execute(f"ALTER TABLE priorities DROP COLUMN {col}")
                conn.commit()
                _log.warning("Auto-migrated: dropped %s from priorities", col)
            except Exception:
                pass
    conn.execute("UPDATE entities SET type = 'group' WHERE type = 'organization'")
    conn.commit()

    # Diagnostics
    all_routes = [r.path for r in app.routes if hasattr(r, 'path')]
    agent_routes = [p for p in all_routes if '/agent' in p]
    _log.warning("=== STARTUP DIAGNOSTICS ===")
    _log.warning("Total routes: %d | Agent routes: %d", len(all_routes), len(agent_routes))
    _log.warning("ENV: %s | PORT: %s",
                 os.getenv("PRAXIS_ENV", "(default)"),
                 os.getenv("PORT", "(default)"))
    if agent_routes:
        _log.warning("Agent paths: %s", ", ".join(sorted(set(agent_routes))))
    else:
        _log.warning("NO AGENT ROUTES REGISTERED")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(priorities)").fetchall()]
    missing = [c for c in ("description", "last_engaged_at", "agent_context") if c not in cols]
    if missing:
        _log.warning("DB schema missing columns: %s", missing)
    else:
        _log.warning("DB schema OK")
    _log.warning("=== END DIAGNOSTICS ===")

# -----------------------------------------------------------------------------
# Agent API (mounted directly — shared auth, shared cache)
# -----------------------------------------------------------------------------

try:
    from praxis_core.agent_api.priorities import router as agent_priority_router
    from praxis_core.agent_api.tasks import router as agent_task_router
    from praxis_core.agent_api.rules import router as agent_rule_router
    from praxis_core.agent_api.graph import router as agent_graph_router
    app.include_router(agent_priority_router, prefix="/agent/priorities", tags=["agent"])
    app.include_router(agent_task_router, prefix="/agent/tasks", tags=["agent"])
    app.include_router(agent_rule_router, prefix="/agent/rules", tags=["agent"])
    app.include_router(agent_graph_router, prefix="/agent/graph", tags=["agent"])
    _agent_routes = [r for r in app.routes if hasattr(r, 'path') and '/agent' in r.path]
    _log.warning("Agent API: %d routes mounted", len(_agent_routes))
except Exception:
    _log.exception("Failed to load agent API")


@app.post("/agent/auth/login")
async def agent_login(request: Request):
    """Agent login — returns bearer token."""
    from praxis_core.persistence import authenticate_user, create_session
    from praxis_core.model.users import SessionType

    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")

    user = authenticate_user(username, password)
    if user is None:
        return JSONResponse(
            {"error": "Invalid username or password"},
            status_code=401,
        )

    session = create_session(
        user_id=user.id,
        session_type=SessionType.API,
        user_agent=request.headers.get("User-Agent"),
    )

    return {
        "token": session.id,
        "user_id": user.id,
        "username": user.username,
        "entity_id": user.entity_id,
    }


# -----------------------------------------------------------------------------
# Web UI Routes
# -----------------------------------------------------------------------------

from praxis_web.routes.auth import router as auth_router
from praxis_web.routes.pages import router as pages_router
from praxis_web.routes.priorities import router as priorities_router
from praxis_web.routes.priority_tree import router as priority_tree_router
from praxis_web.routes.priority_detail import router as priority_detail_router
from praxis_web.routes.priority_actions import router as priority_actions_router
from praxis_web.routes.tasks import router as tasks_router
from praxis_web.routes.rules import router as rules_router
from praxis_web.routes.sharing import router as sharing_router
from praxis_web.routes.tags import router as tags_router
from praxis_web.routes.filters import router as filters_router
from praxis_web.routes.chips import router as chips_router
from praxis_web.routes.triggers import router as triggers_router
from praxis_web.routes.settings import router as settings_router

app.include_router(auth_router)
app.include_router(pages_router)
app.include_router(priorities_router)
app.include_router(priority_tree_router)
app.include_router(priority_detail_router)
app.include_router(priority_actions_router)
app.include_router(tasks_router)
app.include_router(rules_router)
app.include_router(sharing_router)
app.include_router(tags_router)
app.include_router(filters_router)
app.include_router(chips_router)
app.include_router(triggers_router)
app.include_router(settings_router)
