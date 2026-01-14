
import os
import sys
import django
from dotenv import load_dotenv
import re

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def setup_django():
    # Load core env
    load_dotenv("backends/core/.env")
    # ensure backends/core is in path
    core_path = os.path.dirname(os.path.abspath(__file__))
    if core_path not in sys.path:
        sys.path.insert(0, core_path)
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lawa_platform.settings')
    django.setup()

def get_pinecone_index():
    # Load indexing env for Pinecone
    load_dotenv("../indexing/.env")
    
    api_key = os.getenv("PINECONE_API_KEY")
    index_name = os.getenv("PINECONE_INDEX_NAME")
    
    if not api_key or not index_name:
        print("Error: Could not load PINECONE_API_KEY or PINECONE_INDEX_NAME")
        return None
    
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=api_key)
        return pc.Index(index_name)
    except Exception as e:
        print(f"Error connecting to Pinecone: {e}")
        return None

def fix_namespaces():
    setup_django()
    from apps.sites.models import Site
    
    index = get_pinecone_index()
    if not index:
        return

    print("Fetching Pinecone stats...")
    try:
        stats = index.describe_index_stats()
        pinecone_namespaces = stats.namespaces.keys()
    except Exception as e:
        print(f"Failed to get index stats: {e}")
        return

    print(f"Found {len(pinecone_namespaces)} namespaces in Pinecone.")
    
    sites = Site.objects.all()
    print(f"Checking {sites.count()} sites...")
    
    updated_count = 0
    
    for site in sites:
        site_prefix = f"site_{site.id}_"
        
        # Find all namespaces for this site
        # Format: site_{uuid}_{timestamp}
        matching_ns = [ns for ns in pinecone_namespaces if ns.startswith(site_prefix)]
        
        if not matching_ns:
            # Fallback check for legacy format site_{uuid}
            legacy_ns = f"site_{site.id}"
            if legacy_ns in pinecone_namespaces:
                matching_ns = [legacy_ns]
            else:
                print(f"Site {site.domain} ({site.id}): No vectors found in Pinecone. Skipping.")
                continue
                
        # Sort by timestamp (if present) to find latest
        # Just alpha sort works for timestamp if length is constant, but better to extract
        def extract_ts(ns):
            parts = ns.split('_')
            if len(parts) >= 3 and parts[-1].isdigit():
                return int(parts[-1])
            return 0
            
        latest_ns = sorted(matching_ns, key=extract_ts, reverse=True)[0]
        
        current_active = site.active_namespace
        
        if current_active != latest_ns:
            print(f"MISMATCH: Site {site.domain} ({site.id})")
            print(f"  DB Active: {current_active}")
            print(f"  Pinecone : {latest_ns} (Latest of {len(matching_ns)})")
            
            site.active_namespace = latest_ns
            site.save(update_fields=['active_namespace'])
            print(f"  FIXED: Updated DB to {latest_ns}")
            updated_count += 1
        else:
            # check if it matches legacy default
            print(f"OK: Site {site.domain} is synced ({latest_ns})")

    print(f"\nDone. Fixed {updated_count} sites.")

if __name__ == "__main__":
    fix_namespaces()
