"""
Praxis Web UI server.

Run with: uvicorn praxis_web.app:app --port 8080
Requires: PRAXIS_API_URL environment variable (default: http://localhost:8000)
"""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import httpx

from praxis_web.rendering import API_URL, PRAXIS_ENV

# -----------------------------------------------------------------------------
# App Setup
# -----------------------------------------------------------------------------

_log = logging.getLogger("praxis.web")

app = FastAPI(title="Praxis Web")

# Static files
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# -----------------------------------------------------------------------------
# Agent API (mounted directly — no proxy, shared auth)
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
    """Agent login — returns bearer token. Proxies to internal API."""
    body = await request.json()
    async with httpx.AsyncClient(base_url=API_URL, timeout=30.0) as client:
        response = await client.post("/api/auth/login", json=body)
        return Response(content=response.content, status_code=response.status_code,
                        media_type="application/json")


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


# -----------------------------------------------------------------------------
# Startup Diagnostics
# -----------------------------------------------------------------------------

@app.on_event("startup")
async def _startup_diagnostics():
    """Log diagnostic info for debugging deployment issues."""
    all_routes = [r.path for r in app.routes if hasattr(r, 'path')]
    agent_routes = [p for p in all_routes if '/agent' in p]
    _log.warning("=== STARTUP DIAGNOSTICS ===")
    _log.warning("Total routes: %d | Agent routes: %d", len(all_routes), len(agent_routes))
    _log.warning("API_URL: %s | ENV: %s | PORT: %s",
                 os.getenv("PRAXIS_API_URL", "(default)"),
                 os.getenv("PRAXIS_ENV", "(default)"),
                 os.getenv("PORT", "(default)"))
    if agent_routes:
        _log.warning("Agent paths: %s", ", ".join(sorted(set(agent_routes))))
    else:
        _log.warning("NO AGENT ROUTES REGISTERED")
    try:
        from praxis_core.persistence import get_connection
        conn = get_connection()
        cols = [row[1] for row in conn.execute("PRAGMA table_info(priorities)").fetchall()]
        missing = [c for c in ("description", "last_engaged_at", "agent_context") if c not in cols]
        if missing:
            _log.warning("DB schema missing columns: %s", missing)
        else:
            _log.warning("DB schema OK (priorities table has all expected columns)")
    except Exception:
        _log.exception("DB schema check failed")
    _log.warning("=== END DIAGNOSTICS ===")
