.PHONY: help build up down logs shell migrate superuser test clean

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build Docker images
	docker-compose build

up: ## Start all services
	docker-compose up -d

down: ## Stop all services
	docker-compose down

logs: ## Show logs
	docker-compose logs -f

shell: ## Open Django shell
	docker-compose exec web python manage.py shell

migrate: ## Run database migrations
	docker-compose exec web python manage.py migrate

makemigrations: ## Create new migrations
	docker-compose exec web python manage.py makemigrations

superuser: ## Create superuser
	docker-compose exec web python manage.py createsuperuser

test: ## Run tests
	docker-compose exec web python manage.py test

test-coverage: ## Run tests with coverage
	docker-compose exec web python -m pytest --cov=. --cov-report=html

clean: ## Clean up containers and volumes
	docker-compose down -v
	docker system prune -f

dev-setup: ## Set up development environment
	cp env.example .env
	docker-compose up -d db redis
	sleep 10
	docker-compose exec web python manage.py migrate
	docker-compose exec web python manage.py createsuperuser
	@echo "Development environment ready! Run 'make up' to start all services."

seed: ## Seed database with sample data
	docker-compose exec web python manage.py seed_data

worker: ## Start background worker
	docker-compose exec web python manage.py worker
