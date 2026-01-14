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
    # If user already exists (from previous run without db flush), we can try to login
    if resp.status_code != 201:
         if "already exists" in resp.text:
             pass # Proceed to login
         else:
             assert resp.status_code == 201, f"Signup failed: {resp.text}"
    
    # Verify user via management command to ensure we hit the same DB as the running server
    # (Pytest might be using a separate test DB, but the server is using the persistent one)
    import subprocess
    import sys
    
    email = auth_data['email']
    verify_script = (
        f"from django.contrib.auth import get_user_model; "
        f"User = get_user_model(); "
        f"print(f'Attempting to verify {{User.objects.filter(email=\"{email}\").count()}} users'); "
        f"u = User.objects.get(email='{email}'); "
        f"u.is_active = True; "
        f"u.is_email_verified = True; "
        f"u.save(); "
        f"print('Verification successful')"
    )
    
    # Run in the same environment (backend dir) using the same settings
    cmd = [
        sys.executable, "manage.py", "shell", 
        "-c", verify_script
    ]
    env = os.environ.copy()
    env['DJANGO_SETTINGS_MODULE'] = 'lawa_platform.settings'
    
    try:
        proc = subprocess.run(
            cmd, 
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), # Go up to backend root
            capture_output=True, 
            text=True, 
            env=env,
            check=True
        )
        print(f"User verification output: {proc.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to verify user: {e.stdout} {e.stderr}")
        raise
    
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
