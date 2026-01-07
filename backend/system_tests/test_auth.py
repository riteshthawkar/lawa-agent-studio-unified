import pytest
import uuid

def test_signup_success(api_session, base_url):
    username = f"test_{uuid.uuid4().hex[:8]}"
    payload = {
        "email": f"{username}@example.com",
        "username": username,
        "password": "Password123!",
        "password_confirm": "Password123!",
        "name": "Unit Test User"
    }
    resp = api_session.post(f"{base_url}/v1/auth/signup/", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    # Djoser might return the user object directly or wrap it
    if "user" in data:
         assert data["user"]["email"] == payload["email"]
    else:
         assert data["email"] == payload["email"]

def test_login_invalid_credentials(api_session, base_url):
    payload = {
        "email": "nonexistent@example.com",
        "password": "wrongpassword"
    }
    resp = api_session.post(f"{base_url}/v1/auth/login/", json=payload)
    assert resp.status_code in [400, 401]
    
def test_access_protected_route_without_token(api_session, base_url):
    # Try to list sites without token
    resp = api_session.get(f"{base_url}/v1/sites/")
    assert resp.status_code in [401, 403]
