from .settings import *

# Override Email Backend for Testing to prevent SSL errors
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'

# Ensure Testing flag is set
TESTING = True

# Override Indexing Service URL (User running on 8001)
INDEXING_API_BASE = 'http://127.0.0.1:8001'

# Disable throttling for tests to prevent 429 errors
REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
    'anon': '10000/hour',
    'user': '10000/hour',
    'organization': '10000/hour',
    'tiered_organization': '10000/hour',
    'burst': '10000/minute',
    'sustained': '100000/day',
    'indexing': '10000/hour',
    'indexing_anon': '10000/hour',
    'chatbot': '10000/hour',
    'chatbot_anon': '10000/hour',
    'frontend': '10000/hour',
    'sites': '10000/hour',
    'expensive': '10000/hour',
    'bulk_operations': '10000/hour',
    'file_upload': '10000/hour',
    'report_generation': '10000/day',
}

# Force local database for testing to avoid PROD connection
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'lawa-indexing-database',
        'USER': 'ritesh.thawkar',
        'PASSWORD': '',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
