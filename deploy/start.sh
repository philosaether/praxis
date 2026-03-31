#!/bin/bash
set -e

# Start the API server in the background
echo "Starting API server on :8000..."
uvicorn praxis_core.api.app:app --host 0.0.0.0 --port 8000 &

# Wait for API to be ready
sleep 2

# Start the Web server in the foreground
# Use PORT env var if set (Railway), otherwise default to 8080
WEB_PORT=${PORT:-8080}
echo "Starting Web server on :$WEB_PORT..."
exec uvicorn praxis_web.app:app --host 0.0.0.0 --port $WEB_PORT
