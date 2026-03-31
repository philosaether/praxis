FROM python:3.11-slim

WORKDIR /app

# Copy source code and config
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Install the package and dependencies
RUN pip install --no-cache-dir .

# Create data directory for SQLite
RUN mkdir -p /data

# Environment variables
ENV PYTHONPATH=/app/src
ENV PRAXIS_DB_PATH=/data/praxis.db
ENV PRAXIS_API_URL=http://localhost:8000

# Expose port (Railway sets PORT dynamically)
EXPOSE 8080

# Start script runs both API and Web servers
COPY deploy/start.sh ./
RUN chmod +x start.sh

CMD ["./start.sh"]
