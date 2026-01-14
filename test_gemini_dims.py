
import os
import asyncio
import aiohttp
import json
from dotenv import load_dotenv

load_dotenv("backends/indexing/.env")

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    print("Error: GEMINI_API_KEY not found in backends/indexing/.env")
    exit(1)

async def test_embedding():
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent"
    headers = {
        "x-goog-api-key": API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "models/gemini-embedding-001",
        "content": {"parts": [{"text": "Hello world"}]},
        "output_dimensionality": 3072
    }
    
    print(f"Sending request to {url} with dim=3072...")
    
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status != 200:
                print(f"Error: {response.status}")
                print(await response.text())
                return
            
            result = await response.json()
            if "embedding" in result:
                values = result["embedding"]["values"]
                print(f"Success! Received embedding.")
                print(f"Dimension: {len(values)}")
            else:
                print("No embedding in response")
                print(result)

if __name__ == "__main__":
    asyncio.run(test_embedding())
