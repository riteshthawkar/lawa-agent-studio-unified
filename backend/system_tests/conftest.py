import pytest
import requests
import uuid
import os

BASE_URL = os.getenv("TEST_API_BASE", "http://127.0.0.1:8000")

@pytest.fixture(scope="session")
def base_url():
    return BASE_URL

@pytest.fixture(scope="session")
def api_session(base_url):
    """Session with common headers but no auth"""
    session = requests.Session()
    # session.headers.update({"Content-Type": "application/json"})
    return session

@pytest.fixture(scope="session")
def auth_data():
    username = f"system_test_{uuid.uuid4().hex[:8]}"
    return {
        "email": f"{username}@test.com",
        "username": username,
        "password": "TestPassword123!",
        "password_confirm": "TestPassword123!",
        "name": "System Test User"
    }

@pytest.fixture(scope="session")
def auth_token(api_session, base_url, auth_data):
    # Register
    signup_url = f"{base_url}/v1/auth/signup/"
    resp = api_session.post(signup_url, json=auth_data)
    assert resp.status_code == 201, f"Signup failed: {resp.text}"
    
    # Login
    login_url = f"{base_url}/v1/auth/login/"
    login_payload = {
        "email": auth_data["email"],
        "password": auth_data["password"]
    }
    resp = api_session.post(login_url, json=login_payload)
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    
    data = resp.json()
    token = data.get('tokens', {}).get('access')
    assert token, "No access token in login response"
    return token

@pytest.fixture(scope="session")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}
