FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy application code
COPY src/ ./src/

# Create data directory for SQLite
RUN mkdir -p /data

# Environment variables
ENV PYTHONPATH=/app/src
ENV PRAXIS_DB_PATH=/data/praxis.db
ENV PRAXIS_API_URL=http://localhost:8000

# Expose ports
EXPOSE 8080

# Start script runs both API and Web servers
COPY deploy/start.sh ./
RUN chmod +x start.sh

CMD ["./start.sh"]
