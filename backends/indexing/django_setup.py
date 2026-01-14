#!/usr/bin/env python3
"""
Django Configuration for FastAPI Indexing Backend
Sets up Django ORM for use in FastAPI application.
"""

import os
import sys
import django
from pathlib import Path

def setup_django():
    """Initialize Django for use in FastAPI backend."""
    
    # Add the backend directory to Python path
    backend_path = Path(__file__).parent.parent / "core"
    sys.path.insert(0, str(backend_path))
    
    # Ensure logs directory exists to prevent startup error
    logs_dir = backend_path / "logs"
    logs_dir.mkdir(exist_ok=True)
    
    # Set Django settings module
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lawa_platform.settings')
    
    # Initialize Django
    django.setup()
    
    print("✅ Django ORM initialized successfully in FastAPI backend")

def get_django_models():
    """Import and return Django models after setup."""
    try:
        from apps.indexing.models import IndexingJob, IndexedPage
        from apps.sites.models import Site
        from apps.chatbot.models import Chatbot

        return {
            'IndexingJob': IndexingJob,
            'IndexedPage': IndexedPage,
            'Site': Site,
            'Chatbot': Chatbot
        }
    except ImportError as e:
        print(f"❌ Failed to import Django models: {e}")
        raise

# Initialize Django when module is imported
setup_django()
