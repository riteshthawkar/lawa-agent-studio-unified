import pytest
import asyncio
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """Test the root endpoint returns correct metadata"""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert "version" in data

@pytest.mark.asyncio
async def test_api_docs_accessible(client: AsyncClient):
    """Test standard FastAPI docs endpoints exist"""
    response_docs = await client.get("/docs")
    assert response_docs.status_code == 200
    
    response_redoc = await client.get("/redoc")
    assert response_redoc.status_code == 200
