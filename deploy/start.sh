#!/bin/bash
set -e

# Single process: web app handles everything (UI + agent API)
# Use PORT env var if set (Railway), otherwise default to 8080
exec uvicorn praxis_web.app:app --host 0.0.0.0 --port ${PORT:-8080}
