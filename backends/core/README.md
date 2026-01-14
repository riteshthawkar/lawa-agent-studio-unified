# Lawa Platform Backend

A production-ready MVP Platform Backend for Lawa Webbotify that manages authentication, organizations, sites, chatbots, chat sessions, usage tracking, and orchestration with external services.

## 🚀 Current Status: PRODUCTION READY

**✅ All critical endpoints are working and tested!**

- ✅ **Authentication System**: JWT + API Key authentication fully functional
- ✅ **Dashboard Stats**: Real-time statistics and monitoring working
- ✅ **Site Management**: Create, verify, and manage websites successfully
- ✅ **Chatbot Management**: Full CRUD operations for AI chatbots
- ✅ **Chat Sessions**: Complete chat session management
- ✅ **Database**: All relationships and migrations applied correctly
- ✅ **API Documentation**: Swagger UI available at `/api/docs/`

**Server Running**: `http://0.0.0.0:8001` (Port 8001 to avoid conflict with website-indexing-backend)

## Features

- **Multi-tenant Architecture**: Organization-based data isolation
- **Authentication**: JWT + API Key authentication with scoped permissions
- **Site Management**: Domain verification and indexing orchestration
- **Chatbot Management**: AI chatbot configuration and styling
- **Chat System**: Session-based chat with message persistence
- **Usage Tracking**: Quota management and usage analytics
- **Background Jobs**: PostgreSQL-backed job processing (no Redis required)
- **Webhook Handling**: Secure webhook processing for external service integration
- **API Documentation**: Auto-generated OpenAPI/Swagger documentation

## Tech Stack

- **Framework**: Django 4.2 + Django REST Framework
- **Database**: PostgreSQL with UUID primary keys
- **Authentication**: JWT (SimpleJWT) + API Keys
- **Background Jobs**: PostgreSQL outbox pattern (Redis optional)
- **API Documentation**: drf-spectacular
- **Containerization**: Docker + Docker Compose

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)

### Development Setup

1. **Clone and setup**:
   ```bash
   git clone <repository>
   cd backend
   cp env.example .env
   ```

2. **Start services**:
   ```bash
   make dev-setup  # First time setup
   make up         # Start all services
   ```

3. **Access the application**:
   - API: http://localhost:8001
   - API Documentation: http://localhost:8001/api/docs/
   - Admin: http://localhost:8001/admin/

### Current Working Setup

**✅ Server is running and all endpoints are functional!**

```bash
# Start the server (if not already running)
source venv/bin/activate
python manage.py runserver 0.0.0.0:8001
```

**Test the API:**
```bash
# Test authentication
curl -X POST http://0.0.0.0:8001/v1/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "testpass123"}'

# Test dashboard stats (with JWT token)
curl -X GET http://0.0.0.0:8001/v1/frontend/dashboard/stats/ \
  -H "Authorization: Bearer <JWT_TOKEN>"
```

### Environment Variables

Copy `env.example` to `.env` and configure:

```bash
# Database
DB_NAME=lawa_platform
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432

# Authentication
AUTH_JWT_SECRET=your-super-secret-jwt-key
AUTH_JWT_ACCESS_TOKEN_LIFETIME=3600
AUTH_JWT_REFRESH_TOKEN_LIFETIME=86400

# External Services
INDEXING_API_BASE=http://localhost:8001
INDEXING_API_TOKEN=your-indexing-service-token
CHATBOT_API_BASE=http://localhost:8002
CHATBOT_API_TOKEN=your-chatbot-service-token

# Pinecone
PINECONE_API_KEY=your-pinecone-api-key
DEFAULT_PINECONE_INDEX=default-index

# Webhooks
WEBHOOK_SIGNING_SECRET=your-webhook-signing-secret

# Redis (Optional)
USE_REDIS=false
REDIS_URL=redis://localhost:6379/0
```

## API Endpoints

### Authentication & Organizations

- `POST /v1/auth/signup` - User registration
- `POST /v1/auth/login` - User login
- `GET /v1/auth/me` - Current user profile
- `POST /v1/orgs` - Create organization
- `GET /v1/orgs/:orgId` - Organization details
- `POST /v1/orgs/:orgId/api-keys` - Create API key

### Sites & Verification

- `POST /v1/orgs/:orgId/sites` - Create site
- `GET /v1/orgs/:orgId/sites` - List sites
- `POST /v1/sites/:siteId/verify` - Verify site ownership
- `GET /v1/sites/:siteId/verification-instructions` - Get verification instructions

### Indexing Orchestration

- `POST /v1/sites/:siteId/indexing-jobs` - Create indexing job
- `GET /v1/sites/:siteId/indexing-jobs` - List site indexing jobs
- `GET /v1/indexing-jobs/:jobId` - Get indexing job details
- `POST /v1/webhooks/indexing` - Indexing service webhook

### Chatbots & Chat

- `POST /v1/sites/:siteId/chatbots` - Create chatbot
- `GET /v1/sites/:siteId/chatbots` - List chatbots
- `GET /v1/chatbots/:chatbotId/style` - Get chatbot style
- `PUT /v1/chatbots/:chatbotId/style` - Update chatbot style
- `POST /v1/chatbots/:chatbotId/sessions` - Create chat session
- `POST /v1/chat/sessions/:sessionId/messages` - Send message
- `GET /v1/chat/sessions/:sessionId/messages` - Get session messages

### Usage & Quotas

- `GET /v1/orgs/:orgId/usage` - Organization usage
- `GET /v1/orgs/:orgId/quotas` - Organization quotas

## Data Model

### Core Entities

- **Users**: Custom user model with email-based authentication
- **Organizations**: Multi-tenant organization management
- **Memberships**: User-organization relationships with roles
- **Sites**: Website management with verification
- **Chatbots**: AI chatbot configuration and styling
- **ChatSessions**: Chat conversation management
- **ChatMessages**: Individual chat messages with citations
- **IndexingJobs**: External indexing service job tracking
- **UsageEvents**: Usage tracking and analytics
- **Quotas**: Organization quota management

### Multi-tenancy

All data is isolated by `org_id`. Every request is scoped to the user's organization context.

## Background Jobs

The system uses a PostgreSQL-backed outbox pattern for reliable background job processing:

- **No Redis Required**: Uses database for job queuing
- **Reliable Processing**: ACID transactions ensure job delivery
- **Retry Logic**: Exponential backoff with configurable max attempts
- **Webhook Delivery**: Reliable webhook delivery to external services

### Running Background Worker

```bash
# Using Docker Compose
make worker

# Or directly
python manage.py worker
```

## Security

- **JWT Authentication**: Secure token-based authentication
- **API Key Authentication**: Scoped API keys for service integration
- **Organization Isolation**: Strict data isolation between organizations
- **Webhook Security**: HMAC signature verification
- **Input Validation**: Comprehensive request validation
- **Rate Limiting**: Built-in rate limiting (configurable)

## Development

### Running Tests

```bash
make test
make test-coverage
```

### Database Migrations

```bash
make makemigrations
make migrate
```

### Creating Superuser

```bash
make superuser
```

### Seeding Sample Data

```bash
make seed
```

## Production Deployment

### Docker Deployment

1. **Build and deploy**:
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```

2. **Run migrations**:
   ```bash
   docker-compose exec web python manage.py migrate
   ```

3. **Collect static files**:
   ```bash
   docker-compose exec web python manage.py collectstatic --noinput
   ```

### Environment Configuration

For production, ensure:

- `DEBUG=False`
- `SECRET_KEY` is set to a secure random value
- `AUTH_JWT_SECRET` is set to a secure random value
- `WEBHOOK_SIGNING_SECRET` is set to a secure random value
- Database credentials are properly configured
- External service URLs and tokens are configured

## External Service Integration

### Indexing Service

The platform integrates with an external indexing service:

- **Endpoint**: `POST {INDEXING_API_BASE}/index`
- **Authentication**: Bearer token via `INDEXING_API_TOKEN`
- **Webhook**: Receives status updates via `POST /v1/webhooks/indexing`

### Chatbot Service

The platform integrates with an external chatbot service:

- **Endpoint**: `POST {CHATBOT_API_BASE}/chat`
- **Authentication**: Bearer token via `CHATBOT_API_TOKEN`
- **Namespace**: Uses tenant-specific namespaces for data isolation

## Monitoring & Observability

- **Structured Logging**: JSON logs with request IDs and organization context
- **Request Tracking**: Unique request IDs for tracing
- **Error Handling**: Comprehensive error handling with detailed error codes
- **Health Checks**: Built-in health check endpoints

## API Documentation

Interactive API documentation is available at:

- **Swagger UI**: http://localhost:8000/api/docs/
- **ReDoc**: http://localhost:8000/api/redoc/
- **OpenAPI Schema**: http://localhost:8000/api/schema/

## License

This project is proprietary software. All rights reserved.
