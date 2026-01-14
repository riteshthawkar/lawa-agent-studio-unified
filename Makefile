# =============================================================================
# Lawa Agent Studio - Makefile
# =============================================================================
# Unified commands for development, testing, and deployment
# =============================================================================

.PHONY: help test test-core test-indexing test-widget test-frontend test-quick \
        install install-core install-indexing install-frontend \
        run run-core run-indexing run-widget dev clean lint format

# Default target
help:
	@echo ""
	@echo "╔═══════════════════════════════════════════════════════════════════╗"
	@echo "║             🚀 LAWA AGENT STUDIO - COMMANDS                       ║"
	@echo "╚═══════════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "  Testing:"
	@echo "    make test            Run all tests with terminal UI"
	@echo "    make test-core       Run Django backend tests"
	@echo "    make test-indexing   Run indexing service tests"
	@echo "    make test-widget     Run widget backend tests"
	@echo "    make test-frontend   Run frontend Playwright tests"
	@echo "    make test-quick      Run quick smoke tests"
	@echo "    make test-coverage   Run tests with coverage report"
	@echo ""
	@echo "  Development:"
	@echo "    make install         Install all dependencies"
	@echo "    make run             Run all services (Docker)"
	@echo "    make dev             Run development servers"
	@echo "    make lint            Run linters"
	@echo "    make format          Format code"
	@echo "    make clean           Clean generated files"
	@echo ""
	@echo "  Deployment:"
	@echo "    make build           Build Docker images"
	@echo "    make deploy          Deploy to production"
	@echo ""

# =============================================================================
# Testing
# =============================================================================

test:
	@./scripts/run_tests.sh all

test-core:
	@./scripts/run_tests.sh core

test-indexing:
	@./scripts/run_tests.sh indexing

test-widget:
	@./scripts/run_tests.sh widget

test-frontend:
	@./scripts/run_tests.sh frontend

test-quick:
	@./scripts/run_tests.sh quick

test-coverage:
	@./scripts/run_tests.sh all --coverage

test-verbose:
	@./scripts/run_tests.sh all --verbose

# Direct pytest commands (no UI)
pytest-core:
	cd backends/core && venv/bin/python -m pytest -v

pytest-indexing:
	cd backends/indexing && env/bin/python -m pytest tests/ -v

# =============================================================================
# Installation
# =============================================================================

install: install-core install-indexing install-widget install-frontend install-widget-frontend
	@echo "✓ All dependencies installed"

install-core:
	@echo "→ Installing Django backend dependencies..."
	cd backends/core && python3 -m venv venv && venv/bin/pip install -r requirements.txt

install-indexing:
	@echo "→ Installing indexing service dependencies..."
	cd backends/indexing && python3 -m venv env && env/bin/pip install -r requirements.txt

install-widget:
	@echo "→ Installing widget backend dependencies..."
	cd backends/widget && python3 -m venv env && env/bin/pip install -r requirements.txt

install-frontend:
	@echo "→ Installing main frontend dependencies..."
	cd frontends/app && npm install

install-widget-frontend:
	@echo "→ Installing widget frontend dependencies..."
	cd frontends/widget && npm install

install-playwright:
	@echo "→ Installing Playwright browsers..."
	cd frontends/app && npx playwright install

# =============================================================================
# Development Servers
# =============================================================================

run:
	docker-compose up -d

run-core:
	cd backends/core && venv/bin/python3 manage.py runserver

run-indexing:
	cd backends/indexing && env/bin/uvicorn app:app --reload --port 8002

run-widget:
	cd backends/widget && python main.py

run-frontend:
	cd frontends/app && npm run dev

dev:
	@echo "Starting development servers..."
	@echo "Run these in separate terminals:"
	@echo "  make run-core      # Django on :8000"
	@echo "  make run-indexing  # Indexing on :8080"
	@echo "  make run-frontend  # Vite on :5173"

# =============================================================================
# Docker
# =============================================================================

build:
	docker-compose build

build-no-cache:
	docker-compose build --no-cache

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

# =============================================================================
# Code Quality
# =============================================================================

lint:
	@echo "→ Linting Python code..."
	cd backends/core && venv/bin/python -m flake8 apps/ --max-line-length=120 || true
	cd backends/indexing && env/bin/python -m flake8 modules/ --max-line-length=120 || true
	@echo "→ Linting JavaScript code..."
	cd frontends/app && npm run lint || true

format:
	@echo "→ Formatting Python code..."
	cd backends/core && venv/bin/python -m black apps/ || true
	cd backends/indexing && env/bin/python -m black modules/ || true
	@echo "→ Formatting JavaScript code..."
	cd frontends/app && npm run format || true

# =============================================================================
# Cleanup
# =============================================================================

clean:
	@echo "→ Cleaning generated files..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	find . -type f -name "*.log" -delete 2>/dev/null || true
	find . -type d -name "node_modules" -prune -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Cleanup complete"

clean-docker:
	docker-compose down -v --rmi local

# =============================================================================
# Database
# =============================================================================

migrate:
	cd backends/core && venv/bin/python manage.py migrate

makemigrations:
	cd backends/core && venv/bin/python manage.py makemigrations

shell:
	cd backends/core && venv/bin/python manage.py shell

# =============================================================================
# Deployment
# =============================================================================

deploy:
	@echo "Deploying to production..."
	docker-compose -f docker-compose.yml build
	docker-compose -f docker-compose.yml up -d
