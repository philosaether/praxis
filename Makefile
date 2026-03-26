.PHONY: css css-watch serve test clean

# SASS compilation
css:
	npx sass src/praxis/ui/static/scss/main.scss src/praxis/ui/static/css/main.css --style=compressed

css-watch:
	npx sass src/praxis/ui/static/scss/main.scss src/praxis/ui/static/css/main.css --watch

# Development server
serve:
	uvicorn praxis.ui.api:app --reload

# Run both CSS watch and server (requires terminal multiplexer or two terminals)
dev: css
	@echo "Run 'make css-watch' in another terminal, then 'make serve'"

# Tests
test:
	pytest

# Clean compiled files
clean:
	rm -f src/praxis/ui/static/css/main.css
	rm -f src/praxis/ui/static/css/main.css.map
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
