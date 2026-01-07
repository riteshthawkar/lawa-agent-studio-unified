# Django Backend Deployment Guide

## Overview
The Lawa Platform Backend is a Django application using PostgreSQL, Redis, and Celery. It is containerized using Docker.

## Configuration
All configuration is managed via environment variables.

### Critical Environment Variables
- `DEBUG`: Set to `False` in production.
- `SECRET_KEY`: Must be a long, random string.
- `ALLOWED_HOSTS`: Comma-separated list of domains (e.g., `api.example.com`).
- `INDEXING_API_BASE`: URL of the indexing service (default: `http://localhost:8080`).
- `DB_...`: Database credentials.

## Deployment with Docker

### Prerequisites
- Docker & Docker Compose installed.
- PostgreSQL database (or use the one in `docker-compose.yml`).
- Redis (or use the one in `docker-compose.yml`).

### Build and Run
```bash
# Build the image
docker compose build

# Run the services
docker compose up -d
```

### Production considerations
- The `web` service runs via **Gunicorn** on port 8000.
- The `worker` service runs Celery.
- Ensure `postgres_data` volume is backed up.
- Run `python manage.py collectstatic` is handled inherent in the Dockerfile, but verify static files serving (using WhiteNoise or a reverse proxy like Nginx).

### Health Checks
- API is available at `http://localhost:8000/api/health/` (if configured) or `/admin/login/`.

## Manual Deployment (No Docker)
1. Install dependencies: `pip install -r requirements.txt`.
2. Configure `.env`.
3. Run migrations: `python manage.py migrate`.
4. Collect static: `python manage.py collectstatic`.
5. Run Gunicorn: `gunicorn lawa_platform.wsgi:application --bind 0.0.0.0:8000`.
