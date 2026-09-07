# Facey development tasks.  Run `make` to see everything available.

PY      := .venv/bin/python
PIP     := .venv/bin/pip
PYTEST  := .venv/bin/pytest
FRONT   := frontend
APPDATA := $(HOME)/Library/Application Support/facey

.DEFAULT_GOAL := help
.PHONY: help setup run dev headless test test-all test-model coverage lint typecheck build check clean reset

help: ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk -F':.*?## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup

setup: .venv $(FRONT)/node_modules build ## Install everything (Python + Node + build UI)
	@echo "Ready. Run: make run"

.venv:
	python3 -m venv .venv
	$(PIP) install -q -U pip wheel setuptools
	$(PIP) install -q -r requirements-dev.txt

$(FRONT)/node_modules: $(FRONT)/package.json
	cd $(FRONT) && npm install
	@touch $@

# ------------------------------------------------------------------ run

run: build ## Launch the desktop app
	$(PY) backend/main.py

dev: $(FRONT)/node_modules ## Launch with hot-reloading UI (Vite dev server)
	@cd $(FRONT) && npm run dev & \
	trap "kill %%1 2>/dev/null" EXIT; \
	sleep 2; $(PY) backend/main.py --dev

headless: ## Run the API only, no window (http://127.0.0.1:8756)
	$(PY) backend/main.py --headless

# ---------------------------------------------------------------- tests

test: ## Run the test suite (no model needed, ~5s)
	$(PYTEST) -m "not model"

test-all: ## Run every test, including the real face-recognition model
	$(PYTEST)

test-model: ## Run only the model-backed tests
	$(PYTEST) -m model

coverage: ## Test suite with a coverage report
	$(PYTEST) --cov=backend --cov-report=term-missing --cov-report=html
	@echo "HTML report: htmlcov/index.html"

lint: $(FRONT)/node_modules ## Lint the frontend
	cd $(FRONT) && npm run lint

typecheck: $(FRONT)/node_modules ## Type-check the frontend
	cd $(FRONT) && npx tsc -b --noEmit

check: test typecheck lint ## Everything CI would run

# --------------------------------------------------------------- build

build: $(FRONT)/node_modules ## Build the production UI bundle
	cd $(FRONT) && npm run build

clean: ## Remove build output and caches
	rm -rf $(FRONT)/dist htmlcov .pytest_cache .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

reset: ## Delete the local database, faces and thumbnails (photos are untouched)
	@printf "Delete %s ? [y/N] " "$(APPDATA)"; read ans; \
	case "$$ans" in [yY]*) rm -rf "$(APPDATA)"; echo "Deleted.";; *) echo "Cancelled.";; esac
