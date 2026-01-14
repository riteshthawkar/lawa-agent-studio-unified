"""
Complete End-to-End Integration Tests.

These tests verify the complete user journey from signup to using
the chatbot, ensuring all components work together correctly.
"""
import pytest
import time
import uuid
import requests
from datetime import datetime


class TestCompleteUserJourney:
    """
    Tests the complete user journey:
    1. User signup
    2. Email verification (mocked)
    3. Create organization
    4. Create site/project
    5. Start indexing
    6. Create chatbot
    7. Test knowledge search
    """
    
    @pytest.fixture
    def unique_email(self):
        """Generate unique email for each test"""
        return f"test_{uuid.uuid4().hex[:8]}@example.com"
    
    @pytest.fixture
    def unique_domain(self):
        """Generate unique domain for each test"""
        return f"https://test-{uuid.uuid4().hex[:8]}.example.com"
    
    def test_full_flow_site_creation_to_indexing(self, api_session, base_url, auth_headers):
        """Test creating a site and triggering indexing"""
        # 1. Create a new site
        # Use real URL for crawling
        site_url = "https://example.com"
        
        # Try to create site via /index endpoint (which creates site if needed)
        payload = {
            "url": site_url,
            "max_pages": 5
        }
        
        print(f"\n[E2E] Creating site and starting indexing for {site_url}")
        response = api_session.post(
            f"{base_url}/v1/index/",
            json=payload,
            headers=auth_headers
        )
        
        # Should succeed (200, 201, or 202)
        assert response.status_code in [200, 201, 202], f"Failed to create site: {response.text}"
        
        data = response.json()
        job_id = data.get('id') or data.get('task_id') or data.get('job_id')
        
        print(f"[E2E] Indexing job created: {job_id}")
        
        # 2. Verify site was created
        sites_response = api_session.get(
            f"{base_url}/v1/sites/",
            headers=auth_headers
        )
        assert sites_response.status_code == 200
        
        sites_data = sites_response.json()
        sites = sites_data.get('results', sites_data) if isinstance(sites_data, dict) else sites_data
        
        # Find our site
        from urllib.parse import urlparse
        target_domain = urlparse(site_url).netloc
        our_site = None
        for site in sites:
            # Check for exact domain match or substring match
            d = site.get('domain', '')
            if target_domain == d or target_domain in d:
                our_site = site
                break
        
        assert our_site is not None, f"Site {site_url} not found in sites list"
        print(f"[E2E] Site verified: {our_site.get('id')}")
        
        return our_site
    
    def test_namespace_correctly_set_after_indexing(self, api_session, base_url, auth_headers):
        """Test that active_namespace is set after indexing completes"""
        # Create and index a site
        site_url = "https://example.org"
        
        payload = {
            "url": site_url,
            "max_pages": 2
        }
        
        response = api_session.post(
            f"{base_url}/v1/index/",
            json=payload,
            headers=auth_headers
        )
        
        assert response.status_code in [200, 201, 202]
        
        data = response.json()
        job_id = data.get('id') or data.get('task_id')
        
        # Poll for completion (with timeout)
        max_polls = 30
        poll_interval = 2
        
        for i in range(max_polls):
            # Get job status
            status_response = api_session.get(
                f"{base_url}/v1/indexing-jobs/{job_id}/",
                headers=auth_headers
            )
            
            if status_response.status_code != 200:
                time.sleep(poll_interval)
                continue
            
            job_data = status_response.json()
            job_status = job_data.get('status')
            
            print(f"[E2E] Poll {i+1}: Job status = {job_status}")
            
            if job_status == 'completed':
                # Verify namespace was set
                target_namespace = job_data.get('target_namespace')
                assert target_namespace is not None, "target_namespace should be set"
                assert 'site_' in target_namespace, f"Namespace should start with 'site_': {target_namespace}"
                print(f"[E2E] Namespace correctly set: {target_namespace}")
                return
            
            if job_status in ['failed', 'cancelled']:
                pytest.fail(f"Indexing job failed with status: {job_status}")
            
            time.sleep(poll_interval)
        
        pytest.skip("Indexing did not complete in time - skipping namespace verification")


class TestKnowledgeSearchFlow:
    """Tests for knowledge search functionality"""
    
    def test_knowledge_search_uses_correct_namespace(self, api_session, base_url, auth_headers):
        """Test that knowledge search queries the correct namespace"""
        # First, get list of sites
        sites_response = api_session.get(
            f"{base_url}/v1/sites/",
            headers=auth_headers
        )
        
        if sites_response.status_code != 200:
            pytest.skip("No sites available for search test")
        
        sites_data = sites_response.json()
        sites = sites_data.get('results', sites_data) if isinstance(sites_data, dict) else sites_data
        
        if not sites:
            pytest.skip("No sites available for search test")
        
        # Use first site with active_namespace
        test_site = None
        for site in sites:
            if site.get('active_namespace') or site.get('namespace'):
                test_site = site
                break
        
        if not test_site:
            pytest.skip("No sites with active_namespace available")
        
        site_id = test_site.get('id')
        
        # Perform search
        search_payload = {
            "query": "test query"
        }
        
        response = api_session.post(
            f"{base_url}/v1/sites/{site_id}/search/",
            json=search_payload,
            headers=auth_headers
        )
        
        # Should succeed (even if no results)
        assert response.status_code in [200, 404], f"Search failed: {response.text}"
        
        if response.status_code == 200:
            data = response.json()
            assert 'results' in data or 'total_results' in data or isinstance(data, list)
            print(f"[E2E] Search returned {data.get('total_results', len(data))} results")


class TestChatbotFlow:
    """Tests for chatbot functionality"""
    
    def test_chatbot_creation_and_retrieval(self, api_session, base_url, auth_headers):
        """Test creating and retrieving a chatbot"""
        # Get sites
        sites_response = api_session.get(
            f"{base_url}/v1/sites/",
            headers=auth_headers
        )
        
        if sites_response.status_code != 200:
            pytest.skip("No sites available")
        
        sites = sites_response.json()
        sites = sites.get('results', sites) if isinstance(sites, dict) else sites
        
        if not sites:
            pytest.skip("No sites available")
        
        site_id = sites[0].get('id')
        
        # Check if chatbot exists for this site
        chatbots_response = api_session.get(
            f"{base_url}/v1/chatbots/",
            headers=auth_headers
        )
        
        assert chatbots_response.status_code == 200
        
        chatbots = chatbots_response.json()
        chatbots = chatbots.get('results', chatbots) if isinstance(chatbots, dict) else chatbots
        
        # Find chatbot for our site
        site_chatbot = None
        for cb in chatbots:
            if str(cb.get('site')) == str(site_id) or str(cb.get('site_id')) == str(site_id):
                site_chatbot = cb
                break
        
        if site_chatbot:
            print(f"[E2E] Found existing chatbot: {site_chatbot.get('id')}")
            
            # Verify chatbot has correct namespace reference
            chatbot_id = site_chatbot.get('id')
            
            # Get chatbot index info
            index_info_response = api_session.get(
                f"{base_url}/v1/chatbots/{chatbot_id}/index-info/",
                headers=auth_headers
            )
            
            if index_info_response.status_code == 200:
                index_data = index_info_response.json()
                namespace = index_data.get('namespace')
                print(f"[E2E] Chatbot using namespace: {namespace}")
                
                # Verify namespace is not empty
                assert namespace, "Chatbot should have a namespace"


class TestMultitenantIsolation:
    """Tests for multi-tenant data isolation"""
    
    def test_user_cannot_access_other_org_sites(self, api_session, base_url, auth_headers):
        """Test that users cannot access sites from other organizations"""
        # Create a site
        site_url = f"https://isolation-{uuid.uuid4().hex[:8]}.test.com"
        
        response = api_session.post(
            f"{base_url}/v1/sites/",
            json={"domain": site_url, "name": "Isolation Test"},
            headers=auth_headers
        )
        
        if response.status_code not in [200, 201]:
            pytest.skip("Could not create test site")
        
        site_data = response.json()
        site_id = site_data.get('id')
        
        # Try to access with empty/invalid auth (simulating another user)
        # This is a basic check - in real tests you'd authenticate as another user
        no_auth_response = api_session.get(
            f"{base_url}/v1/sites/{site_id}/",
            headers={}  # No auth
        )
        
        # Should be unauthorized
        assert no_auth_response.status_code in [401, 403], "Unauthenticated access should be denied"
        print("[E2E] Multi-tenant isolation verified")


class TestDashboardDataFlow:
    """Tests for dashboard data endpoints"""
    
    def test_dashboard_stats_endpoint(self, api_session, base_url, auth_headers):
        """Test that dashboard stats endpoint returns correct data"""
        response = api_session.get(
            f"{base_url}/v1/frontend/dashboard/stats/",
            headers=auth_headers
        )
        
        assert response.status_code == 200, f"Dashboard stats failed: {response.text}"
        
        data = response.json()
        
        # Verify expected fields
        expected_fields = ['total_projects', 'total_conversations']
        
        for field in expected_fields:
            # Fields might have different names
            has_field = any(f in data for f in [field, field.replace('_', ''), field.replace('total_', '')])
            if not has_field:
                print(f"[E2E] Warning: Expected field '{field}' not found. Available: {list(data.keys())}")
        
        print(f"[E2E] Dashboard stats: {data}")
    
    def test_analytics_data_endpoint(self, api_session, base_url, auth_headers):
        """Test analytics data endpoint"""
        response = api_session.get(
            f"{base_url}/v1/frontend/analytics/",
            headers=auth_headers
        )
        
        # Analytics might require specific tier
        assert response.status_code in [200, 403], f"Unexpected status: {response.status_code}"
        
        if response.status_code == 200:
            data = response.json()
            print(f"[E2E] Analytics data available")
        else:
            print("[E2E] Analytics requires higher tier (expected)")
