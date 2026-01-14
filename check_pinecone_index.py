
import os
import sys
from dotenv import load_dotenv
from pinecone import Pinecone

# Load from indexing env where Pinecone config lives
load_dotenv("backends/indexing/.env")

API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("PINECONE_INDEX_NAME")

if not API_KEY or not INDEX_NAME:
    print("Error: Missing PINECONE_API_KEY or PINECONE_INDEX_NAME in backends/indexing/.env")
    sys.exit(1)

print(f"Checking Pinecone Index: {INDEX_NAME}")

try:
    pc = Pinecone(api_key=API_KEY)
    index = pc.Index(INDEX_NAME)
    
    # Get Index Description
    desc = pc.describe_index(INDEX_NAME)
    print(f"\nIndex Description:")
    print(f"  Name: {desc.name}")
    print(f"  Dimension: {desc.dimension}")
    print(f"  Metric: {desc.metric}")
    print(f"  Host: {desc.host}")
    
    # Get Index Stats
    stats = index.describe_index_stats()
    print(f"\nIndex Stats:")
    print(f"  Total Vectors: {stats.total_vector_count}")
    print(f"  Namespaces: {len(stats.namespaces)}")
    for ns, ns_stats in stats.namespaces.items():
        print(f"    - {ns}: {ns_stats.vector_count} vectors")

except Exception as e:
    print(f"\nError connecting to Pinecone: {e}")
