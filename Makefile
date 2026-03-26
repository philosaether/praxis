.PHONY: css css-watch serve-api serve-web test clean

# SASS compilation
css:
	npx sass src/praxis_web/static/scss/main.scss src/praxis_web/static/css/main.css --style=compressed

css-watch:
	npx sass src/praxis_web/static/scss/main.scss src/praxis_web/static/css/main.css --watch

# Run core API (port 8000)
serve-api:
	uvicorn praxis_core.api:app --reload --port 8000

# Run web UI (port 8080)
serve-web:
	PRAXIS_API_URL=http://localhost:8000 uvicorn praxis_web.app:app --reload --port 8080

# Development instructions
dev:
	@echo "Run in two terminals:"
	@echo "  Terminal 1: make serve-api"
	@echo "  Terminal 2: make serve-web"
	@echo ""
	@echo "Then open http://localhost:8080"

# Tests
test:
	pytest

# Clean
clean:
	rm -f src/praxis_web/static/css/main.css
	rm -f src/praxis_web/static/css/main.css.map
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true