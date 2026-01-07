
import os
import sys
import django

# Setup Django environment
sys.path.append('/Users/ritesh.thawkar/Ritesh/lawa-webbotify-project/backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lawa_platform.settings')
django.setup()

# Import modified modules to check for syntax errors
print("Importing apps.indexing.services...")
try:
    from apps.indexing.services import IndexingService
    print("✅ apps.indexing.services imported successfully")
except Exception as e:
    print(f"❌ Failed to import apps.indexing.services: {e}")
    sys.exit(1)
