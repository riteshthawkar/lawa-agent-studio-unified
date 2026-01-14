"""
Django settings for lawa_platform project.
"""

import os
import sys
from pathlib import Path
from datetime import timedelta
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Environment variables
env = environ.Env(
    DEBUG=(bool, False),
    USE_REDIS=(bool, False),
)

# Read .env file
environ.Env.read_env(BASE_DIR / '.env')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DEBUG', default=False)

# SECURITY WARNING: keep the secret key used in production secret!
# Fail fast if SECRET_KEY is not set in production
_secret_key_default = 'django-insecure-dev-only-do-not-use-in-production'
SECRET_KEY = env('SECRET_KEY', default=_secret_key_default)
if SECRET_KEY == _secret_key_default and not DEBUG:
    raise ValueError("SECRET_KEY must be set in production!")

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1', '0.0.0.0'])

# Security: Allow disabling CORS for public APIs if needed (default False)
CORS_ALLOW_ALL_ORIGINS = env.bool('CORS_ALLOW_ALL_ORIGINS', default=False)

# Application definition
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'django_filters',
    'drf_spectacular',
    'django_extensions',
]

LOCAL_APPS = [
    'apps.core',
    'apps.auth',
    'apps.organizations',
    'apps.sites',
    'apps.indexing',
    'apps.chatbot',
    'apps.chat',
    'apps.usage',
    'apps.webhooks',
    'apps.background_jobs',
    'apps.frontend',
    'apps.support',
    'apps.payments',
    'apps.admin_api',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'apps.core.json_middleware.JSONParsingMiddleware',  # Fail fast on bad JSON
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    # 'apps.core.middleware.RequestLoggingMiddleware',
    'apps.core.middleware.OrganizationMiddleware',
    'apps.core.middleware.APIVersionMiddleware',  # Add API version headers
    'apps.core.middleware.SecurityHeadersMiddleware',  # Add security headers
]

ROOT_URLCONF = 'lawa_platform.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'lawa_platform.wsgi.application'

# Database - Using unified environment variable names
# Support SQLite for development (no PostgreSQL setup required)
USE_SQLITE = env.bool('USE_SQLITE', default=False)

if USE_SQLITE:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    # PostgreSQL with comprehensive connection pooling
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('DB_NAME', default=env('LAWA_DB_PG_DATABASE', default='lawa_platform')),
            'USER': env('DB_USER', default=env('LAWA_DB_PG_USER', default='postgres')),
            'PASSWORD': env('DB_PASSWORD', default=env('LAWA_DB_PG_PASSWORD', default='password')),
            'HOST': env('DB_HOST', default=env('LAWA_DB_PG_HOST', default='localhost')),
            'PORT': env('DB_PORT', default=env('LAWA_DB_PG_PORT', default='5432')),
            'OPTIONS': {
                # SSL Configuration
                'sslmode': env('DB_SSLMODE', default='prefer'),  # prefer, require, verify-ca, verify-full
                'connect_timeout': env.int('DB_CONNECT_TIMEOUT', default=10),

                # Connection Pooling Options
                # Note: For production, consider using PgBouncer or pgpool-II
                'options': env('DB_OPTIONS', default='-c statement_timeout=30000'),  # 30s statement timeout
            },
            # Django Connection Pooling
            # Keep connections open for reuse (0 = close immediately, None = persistent)
            'CONN_MAX_AGE': env.int('DB_CONN_MAX_AGE', default=600 if not DEBUG else 0),

            # Health check interval (seconds) - available in Django 4.1+
            'CONN_HEALTH_CHECKS': env.bool('DB_CONN_HEALTH_CHECKS', default=True),

            # Atomic requests - wrap each request in a transaction
            'ATOMIC_REQUESTS': env.bool('DB_ATOMIC_REQUESTS', default=False),

            # Disable server-side cursors for better compatibility with PgBouncer
            'DISABLE_SERVER_SIDE_CURSORS': env.bool('DB_DISABLE_SERVER_SIDE_CURSORS', default=False),
        }
    }

    # Optional: Read replica configuration for scaling reads
    if env('DB_REPLICA_HOST', default=None):
        DATABASES['replica'] = {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': env('DB_NAME', default=env('LAWA_DB_PG_DATABASE', default='lawa_platform')),
            'USER': env('DB_REPLICA_USER', default=env('DB_USER', default='postgres')),
            'PASSWORD': env('DB_REPLICA_PASSWORD', default=env('DB_PASSWORD', default='password')),
            'HOST': env('DB_REPLICA_HOST'),
            'PORT': env('DB_REPLICA_PORT', default='5432'),
            'OPTIONS': DATABASES['default']['OPTIONS'],
            'CONN_MAX_AGE': DATABASES['default']['CONN_MAX_AGE'],
            'CONN_HEALTH_CHECKS': True,
        }

    # Database Router for read replica (optional)
    if 'replica' in DATABASES:
        DATABASE_ROUTERS = ['apps.core.db_router.ReplicaRouter']

# Test database configuration - Use PostgreSQL for tests to avoid migration issues
# if 'test' in sys.argv or 'pytest' in sys.modules:
#     DATABASES['default'] = {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': ':memory:',
#     }

# Custom User Model
AUTH_USER_MODEL = 'lawa_auth.User'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Caching Configuration - MVP: Using local memory cache (no Redis needed)
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'lawa-platform-cache',
        'OPTIONS': {
            'MAX_ENTRIES': 1000,  # Maximum number of cache entries
            'CULL_FREQUENCY': 3,  # Fraction of entries culled when MAX_ENTRIES is reached
        },
        'TIMEOUT': 300,  # 5 minutes default timeout
        'VERSION': 1,
    }
}

# Session configuration - using database for MVP (simpler than cache)
SESSION_ENGINE = 'django.contrib.sessions.backends.db'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'apps.auth.authentication.APIKeyAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'frontend': '500/hour',
        'indexing': '60/minute',
        'indexing_anon': '10/minute',
        'chatbot': '200/hour',
        'chatbot_anon': '50/hour',
    },
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PAGINATION_CLASS': 'apps.core.pagination.StandardResultsSetPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'EXCEPTION_HANDLER': 'apps.core.error_handlers.custom_exception_handler',
}

# JWT Settings
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(seconds=env.int('AUTH_JWT_ACCESS_TOKEN_LIFETIME', default=86400)),  # 24 hours
    'REFRESH_TOKEN_LIFETIME': timedelta(seconds=env.int('AUTH_JWT_REFRESH_TOKEN_LIFETIME', default=604800)),  # 7 days
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': env('AUTH_JWT_ALGORITHM', default='HS256'),
    'SIGNING_KEY': env('AUTH_JWT_SECRET', default=SECRET_KEY),
    'VERIFYING_KEY': None,
    'AUDIENCE': None,
    'ISSUER': None,
    'JWK_URL': None,
    'LEEWAY': 0,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'USER_AUTHENTICATION_RULE': 'rest_framework_simplejwt.authentication.default_user_authentication_rule',
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'TOKEN_USER_CLASS': 'rest_framework_simplejwt.models.TokenUser',
    'JTI_CLAIM': 'jti',
    'SLIDING_TOKEN_REFRESH_EXP_CLAIM': 'refresh_exp',
    'SLIDING_TOKEN_LIFETIME': timedelta(minutes=5),
    'SLIDING_TOKEN_REFRESH_LIFETIME': timedelta(days=1),
}

# CORS settings - Security hardened with environment-based configuration
# In production, CORS_ALLOWED_ORIGINS must be explicitly set in environment variables
if DEBUG:
    # Development: Allow common development origins
    CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        'http://localhost:5173',  # Vite dev server
        'http://127.0.0.1:5173',
        'http://localhost:8080',  # Alternative dev port
        'http://127.0.0.1:8080',
        'http://localhost:3333',  # Python HTTP server (test-website)
        'http://127.0.0.1:3333',
        'http://localhost:5500',  # Live Server
        'http://127.0.0.1:5500',
    ])
else:
    # Production: Require explicit configuration (no defaults for security)
    CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
    if not CORS_ALLOWED_ORIGINS:
        import warnings
        warnings.warn(
            "CORS_ALLOWED_ORIGINS is not set in production. "
            "This will block all cross-origin requests. "
            "Set CORS_ALLOWED_ORIGINS in your environment variables.",
            RuntimeWarning
        )

# Allow cookies/auth headers in cross-origin requests
CORS_ALLOW_CREDENTIALS = env.bool('CORS_ALLOW_CREDENTIALS', default=True)

# Allowed HTTP headers in requests
CORS_ALLOWED_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-api-key',  # Custom API key header
    'x-organization-id',  # Custom organization context header
]

# Allowed HTTP methods
CORS_ALLOWED_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

# Headers exposed to the browser
CORS_EXPOSE_HEADERS = [
    'Content-Type',
    'X-Request-ID',
    'X-RateLimit-Limit',
    'X-RateLimit-Remaining',
    'X-RateLimit-Reset',
]

# Cache preflight requests for 1 hour (production) or 10 minutes (development)
CORS_PREFLIGHT_MAX_AGE = env.int('CORS_PREFLIGHT_MAX_AGE', default=600 if DEBUG else 3600)

# Regex patterns for allowed origins (use cautiously)
# Example: CORS_ALLOWED_ORIGIN_REGEXES = [r'^https://.*\.example\.com$']
CORS_ALLOWED_ORIGIN_REGEXES = env.list('CORS_ALLOWED_ORIGIN_REGEXES', default=[])

# API Documentation - Enhanced OpenAPI/Swagger Configuration
SPECTACULAR_SETTINGS = {
    # Basic Info
    'TITLE': 'Lawa Platform API',
    'DESCRIPTION': '''
    **Lawa Webbotify Platform API**

    Production-ready API for managing websites, chatbots, and AI-powered interactions.

    ## Features
    - Multi-tenant organization support
    - Website indexing and crawling
    - AI chatbot management
    - Real-time chat sessions
    - Usage tracking and analytics

    ## Authentication
    - **JWT Bearer Token**: Include `Authorization: Bearer <token>` header
    - **API Key**: Include `X-API-Key: <key>` header for chatbot operations

    ## Rate Limiting
    - Free tier: 100 requests/hour
    - Starter tier: 1,000 requests/hour
    - Professional tier: 5,000 requests/hour
    - Enterprise tier: 50,000 requests/hour

    ## Multi-tenancy
    All endpoints automatically filter data by your organization membership.
    ''',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': '/v1/',

    # Contact & License
    'CONTACT': {
        'name': 'Lawa Platform Support',
        'email': 'support@lawa.com',
    },
    'LICENSE': {
        'name': 'Proprietary',
    },

    # Security Schemes
    'SECURITY': [
        {'BearerAuth': []},
        {'ApiKeyAuth': []},
    ],
    'APPEND_COMPONENTS': {
        'securitySchemes': {
            'BearerAuth': {
                'type': 'http',
                'scheme': 'bearer',
                'bearerFormat': 'JWT',
                'description': 'JWT authentication token obtained from /auth/login endpoint',
            },
            'ApiKeyAuth': {
                'type': 'apiKey',
                'in': 'header',
                'name': 'X-API-Key',
                'description': 'API key for chatbot operations (obtained from chatbot settings)',
            },
        }
    },

    # Schema Generation
    'SCHEMA_COERCE_PATH_PK_SUFFIX': True,
    'SCHEMA_COERCE_METHOD_NAMES': {
        'retrieve': 'get',
        'list': 'list',
        'create': 'create',
        'update': 'update',
        'partial_update': 'patch',
        'destroy': 'delete',
    },

    # Enum Handling
    'ENUM_NAME_OVERRIDES': {
        'StatusEnum': 'apps.sites.models.SiteStatus',
    },

    # Response & Request
    'SERVE_PERMISSIONS': ['rest_framework.permissions.AllowAny'],  # Schema accessible to all
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': True,
        'filter': True,
        'tryItOutEnabled': True,
    },

    # Tags
    'TAGS': [
        {'name': 'Authentication', 'description': 'User authentication and authorization'},
        {'name': 'Organizations', 'description': 'Organization and membership management'},
        {'name': 'Sites', 'description': 'Website management and configuration'},
        {'name': 'Indexing', 'description': 'Website crawling and indexing operations'},
        {'name': 'Chatbots', 'description': 'Chatbot configuration and management'},
        {'name': 'Chat', 'description': 'Real-time chat sessions and messages'},
        {'name': 'Usage', 'description': 'Usage tracking and analytics'},
        {'name': 'Webhooks', 'description': 'Webhook management and events'},
        {'name': 'Frontend', 'description': 'Frontend dashboard and management APIs'},
    ],

    # Sorting
    'SORT_OPERATIONS': True,
    'SORT_OPERATION_PARAMETERS': True,
}

# External Services Configuration
INDEXING_API_BASE = env('INDEXING_API_BASE', default='http://localhost:8080')
INDEXING_API_TOKEN = env('INDEXING_API_TOKEN', default='')
CHATBOT_API_BASE = env('CHATBOT_API_BASE', default='http://localhost:8002')
CHATBOT_API_TOKEN = env('CHATBOT_API_TOKEN', default='')

# Chatbot Backend Configuration (for embed script generation)
CHATBOT_BACKEND_HOST = env('CHATBOT_BACKEND_HOST', default='localhost')
CHATBOT_BACKEND_PORT = env('CHATBOT_BACKEND_PORT', default='8002')

# Widget CDN Configuration  
WIDGET_CDN_HOST = env('WIDGET_CDN_HOST', default='localhost')
WIDGET_CDN_PORT = env('WIDGET_CDN_PORT', default='')
WIDGET_SCRIPT_PATH = env('WIDGET_SCRIPT_PATH', default='widget.js')

# Backend Base URL for webhooks (Django runs on 8000)
BACKEND_BASE_URL = env('BACKEND_BASE_URL', default='http://localhost:8000')

# Pinecone Configuration - Using unified naming
PINECONE_API_KEY = env('PINECONE_API_KEY', default='')
PINECONE_INDEX_NAME = env('PINECONE_INDEX_NAME', default=env('DEFAULT_PINECONE_INDEX', default='webbotify-index-3072'))

# Stripe Configuration
STRIPE_SECRET_KEY = env('STRIPE_SECRET_KEY', default='')
STRIPE_PUBLISHABLE_KEY = env('STRIPE_PUBLISHABLE_KEY', default='')
STRIPE_WEBHOOK_SECRET = env('STRIPE_WEBHOOK_SECRET', default='')
STRIPE_API_VERSION = env('STRIPE_API_VERSION', default='2023-10-16')

# Stripe Price IDs - Set these after creating products in Stripe Dashboard
STRIPE_PRICES = {
    'basic': env('STRIPE_PRICE_BASIC', default=''),
    'premium': env('STRIPE_PRICE_PREMIUM', default=''),
    'enterprise': env('STRIPE_PRICE_ENTERPRISE', default=''),
}

# Frontend URL for redirects
FRONTEND_URL = env('FRONTEND_URL', default='http://localhost:5173')

# Webhook Configuration
WEBHOOK_SIGNING_SECRET = env('WEBHOOK_SIGNING_SECRET', default='')

# Redis Configuration (Optional)
USE_REDIS = env('USE_REDIS', default=False)
if USE_REDIS:
    REDIS_URL = env('REDIS_URL', default='redis://localhost:6379/0')
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
else:
    # Use database for Celery when Redis is not available
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

# Celery Configuration
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

# Logging Configuration
# Ensure logs directory exists
LOGS_DIR = BASE_DIR / 'logs'
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'json': {
            'format': '{"level": "%(levelname)s", "time": "%(asctime)s", "module": "%(module)s", "message": "%(message)s"}',
        },
        'detailed': {
            'format': '[{asctime}] {levelname} {name} {process:d} {thread:d} {pathname}:{lineno} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'maxBytes': 10 * 1024 * 1024,  # 10MB
            'backupCount': 5,
            'formatter': 'detailed',
        },
        'indexing_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'indexing.log',
            'maxBytes': 10 * 1024 * 1024,  # 10MB
            'backupCount': 5,
            'formatter': 'json',
        },
        'error_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'errors.log',
            'maxBytes': 10 * 1024 * 1024,  # 10MB
            'backupCount': 5,
            'formatter': 'detailed',
            'level': 'ERROR',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': env('LOG_LEVEL', default='INFO'),
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'file'],
            'level': env('LOG_LEVEL', default='INFO'),
            'propagate': False,
        },
        'lawa_platform': {
            'handlers': ['console', 'file'],
            'level': env('LOG_LEVEL', default='INFO'),
            'propagate': False,
        },
        'apps.indexing': {
            'handlers': ['console', 'indexing_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'apps.webhooks': {
            'handlers': ['console', 'indexing_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['error_file'],
            'level': 'ERROR',
            'propagate': False,
        },
        'django.security': {
            'handlers': ['error_file'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}

# Security Settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Production Security Settings
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    
    # Session Security
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    
    # Additional Security Headers
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
    SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
    
    # Content Security Policy
    CSP_DEFAULT_SRC = ("'self'",)
    CSP_SCRIPT_SRC = ("'self'", "'unsafe-inline'")
    CSP_STYLE_SRC = ("'self'", "'unsafe-inline'")
    CSP_IMG_SRC = ("'self'", "data:", "https:")
    CSP_CONNECT_SRC = ("'self'",)
    CSP_FONT_SRC = ("'self'",)
    CSP_OBJECT_SRC = ("'none'",)
    CSP_BASE_URI = ("'self'",)
    CSP_FRAME_ANCESTORS = ("'none'",)

# Rate Limiting - Advanced configuration with organization and user-level controls
RATELIMIT_ENABLE = env.bool('RATELIMIT_ENABLE', default=True)
RATELIMIT_USE_CACHE = 'default'

# Django REST Framework Throttling - Using custom throttle classes
REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES'] = [
    'apps.core.rate_limiting.AnonRateThrottle',  # For anonymous users
    'apps.core.rate_limiting.BurstRateThrottle',  # Prevent rapid bursts
    'apps.core.rate_limiting.TieredOrganizationThrottle',  # Organization-based limits
]

# Rate limits - Environment-based configuration for flexibility
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
    # Anonymous users (by IP)
    'anon': env('RATE_LIMIT_ANON', default='100/hour'),

    # Authenticated users
    'user': env('RATE_LIMIT_USER', default='1000/hour'),

    # Organization-based limits (fallback if no tier-specific limit)
    'organization': env('RATE_LIMIT_ORGANIZATION', default='5000/hour'),
    'tiered_organization': env('RATE_LIMIT_TIERED_ORG', default='1000/hour'),

    # Burst protection (short-term limits)
    'burst': env('RATE_LIMIT_BURST', default='30/minute'),

    # Sustained usage limits (long-term limits)
    'sustained': env('RATE_LIMIT_SUSTAINED', default='10000/day'),

    # Endpoint-specific limits
    'indexing': env('RATE_LIMIT_INDEXING', default='50/hour'),
    'indexing_anon': env('RATE_LIMIT_INDEXING_ANON', default='20/hour'),
    'chatbot': env('RATE_LIMIT_CHATBOT', default='1000/hour'),
    'chatbot_anon': env('RATE_LIMIT_CHATBOT_ANON', default='100/hour'),
    'frontend': env('RATE_LIMIT_FRONTEND', default='2000/hour'),
    'sites': env('RATE_LIMIT_SITES', default='500/hour'),

    # Expensive operations (resource-intensive endpoints)
    'expensive': env('RATE_LIMIT_EXPENSIVE', default='10/hour'),
    'bulk_operations': env('RATE_LIMIT_BULK', default='20/hour'),
    'file_upload': env('RATE_LIMIT_UPLOAD', default='30/hour'),
    'report_generation': env('RATE_LIMIT_REPORTS', default='50/day'),
}

# Cache Configuration
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

# Email Configuration
# Use Console backend for testing to prevent 500 errors
if env.bool('TESTING', default=False):
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_USE_SSL = env.bool('EMAIL_USE_SSL', default=False)  # For port 465
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)
RESEND_API_KEY = env('RESEND_API_KEY', default=None)
EMAIL_TIMEOUT = env.int('EMAIL_TIMEOUT', default=10)  # 10 seconds timeout

# SSL/TLS Configuration for Email
# For production with valid SSL certificates, these should be True
# For development or self-signed certificates, can be relaxed
EMAIL_SSL_CERTFILE = env('EMAIL_SSL_CERTFILE', default=None)
EMAIL_SSL_KEYFILE = env('EMAIL_SSL_KEYFILE', default=None)

# SECURITY: Proper SSL certificate verification (DO NOT DISABLE IN PRODUCTION)
# If you're having SSL issues in development:
# 1. Use a proper email service with valid SSL certificates (recommended)
# 2. For Gmail: Use an app-specific password (not regular password)
# 3. For development only: Set EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend'
#
# NEVER disable SSL verification in production as it opens you to MITM attacks

# Feedback Notification Settings
# List of admin emails to receive feedback notifications
FEEDBACK_ADMIN_EMAILS = env.list('FEEDBACK_ADMIN_EMAILS', default=[])

# File Upload Settings
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10MB

# Session Configuration - Environment-based
SESSION_COOKIE_AGE = env.int('SESSION_COOKIE_AGE', default=86400)  # 24 hours
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=not DEBUG)
SESSION_COOKIE_HTTPONLY = True  # Always enforce for security
SESSION_COOKIE_SAMESITE = env('SESSION_COOKIE_SAMESITE', default='Lax')  # 'Strict', 'Lax', or 'None'
SESSION_COOKIE_NAME = 'lawa_sessionid'  # Custom name for obscurity

# CSRF Configuration - Environment-based
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=not DEBUG)
CSRF_COOKIE_HTTPONLY = True  # Always enforce for security
CSRF_COOKIE_SAMESITE = env('CSRF_COOKIE_SAMESITE', default='Lax')
CSRF_COOKIE_NAME = 'lawa_csrftoken'  # Custom name for obscurity
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=CORS_ALLOWED_ORIGINS)

# Production HTTPS Security Settings - Environment-based
if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=True)
    SECURE_HSTS_SECONDS = env.int('SECURE_HSTS_SECONDS', default=31536000)  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True)
    SECURE_HSTS_PRELOAD = env.bool('SECURE_HSTS_PRELOAD', default=True)
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    # Additional security headers for production
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
    X_FRAME_OPTIONS = 'DENY'  # Prevent clickjacking

# Namespace Configuration for Multi-tenancy
DEFAULT_NAMESPACE_PREFIX = 'tenant_{org_id}__site_{site_id}'

# API Versioning Configuration
API_VERSION = env('API_VERSION', default='1.0')
API_DEPRECATED = env.bool('API_DEPRECATED', default=False)
API_SUNSET_DATE = env('API_SUNSET_DATE', default=None)  # RFC 8594 format: "Sat, 31 Dec 2024 23:59:59 GMT"