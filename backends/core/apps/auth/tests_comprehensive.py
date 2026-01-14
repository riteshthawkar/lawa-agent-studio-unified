"""
Comprehensive tests for Auth endpoints.

These tests cover critical security functionality including:
- Password change
- Account deletion
- API key management
- Email updates
- User preferences
"""
import json
import uuid
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch, MagicMock

from apps.organizations.models import Organization, Membership
from apps.auth.models import APIKey

User = get_user_model()


class AuthTestCase(APITestCase):
    """Base test case for auth tests"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='authtestuser',
            email='auth_test@example.com',
            password='TestPassword123!',
            first_name='Test',
            last_name='User',
            is_email_verified=True
        )
        self.org = Organization.objects.create(
            name="Auth Test Organization",
            slug="auth-test-org"
        )
        Membership.objects.create(
            user=self.user,
            organization=self.org,
            role='owner'
        )
        self.client.force_authenticate(user=self.user)


class PasswordChangeTests(AuthTestCase):
    """Tests for password change endpoint"""
    
    def test_change_password_success(self):
        """Test successful password change"""
        url = reverse('change-password')
        payload = {
            'current_password': 'TestPassword123!',
            'new_password': 'NewSecurePass456!',
            'confirm_password': 'NewSecurePass456!'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify new password works
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewSecurePass456!'))
    
    def test_change_password_wrong_current(self):
        """Test password change with wrong current password"""
        url = reverse('change-password')
        payload = {
            'current_password': 'WrongPassword123!',
            'new_password': 'NewSecurePass456!',
            'confirm_password': 'NewSecurePass456!'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_change_password_mismatch(self):
        """Test password change when new passwords don't match"""
        url = reverse('change-password')
        payload = {
            'current_password': 'TestPassword123!',
            'new_password': 'NewSecurePass456!',
            'confirm_password': 'DifferentPassword789!'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_change_password_weak_password(self):
        """Test password change with weak new password"""
        url = reverse('change-password')
        payload = {
            'current_password': 'TestPassword123!',
            'new_password': '123',
            'confirm_password': '123'
        }
        
        response = self.client.post(url, payload, format='json')
        
        # Should reject weak passwords
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY])
    
    def test_change_password_requires_auth(self):
        """Test that password change requires authentication"""
        self.client.force_authenticate(user=None)
        
        url = reverse('change-password')
        payload = {
            'current_password': 'TestPassword123!',
            'new_password': 'NewSecurePass456!',
            'confirm_password': 'NewSecurePass456!'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AccountDeletionTests(AuthTestCase):
    """Tests for account deletion endpoint"""
    
    def test_delete_account_success(self):
        """Test successful account deletion"""
        url = reverse('delete-account')
        payload = {
            'password': 'TestPassword123!',
            'confirmation': 'DELETE MY ACCOUNT'
        }
        
        user_id = self.user.id
        
        response = self.client.delete(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify user is deleted or deactivated
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        # User should be deleted or is_active=False
        try:
            user = User.objects.get(id=user_id)
            # If user exists, should be deactivated
            self.assertFalse(user.is_active)
        except User.DoesNotExist:
            # User deleted - also valid
            pass
    
    def test_delete_account_wrong_password(self):
        """Test account deletion with wrong password"""
        url = reverse('delete-account')
        payload = {
            'password': 'WrongPassword!',
            'confirmation': 'DELETE'
        }
        
        response = self.client.delete(url, payload, format='json')
        
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_403_FORBIDDEN])
        
        # User should still exist
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
    
    def test_delete_account_missing_confirmation(self):
        """Test account deletion without confirmation"""
        url = reverse('delete-account')
        payload = {
            'password': 'TestPassword123!'
        }
        
        response = self.client.delete(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class APIKeyManagementTests(AuthTestCase):
    """Tests for API key management"""
    
    def test_create_api_key(self):
        """Test creating a new API key"""
        url = reverse('api-key-list')
        payload = {
            'name': 'Test API Key',
            'scopes': ['indexing:write']
        }
        
        # Add Organization Header
        self.client.credentials(HTTP_X_ORG_ID=str(self.org.id))
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('token', response.data)  # Token returned on creation
        self.assertEqual(response.data['name'], 'Test API Key')
    
    def test_list_api_keys(self):
        """Test listing API keys"""
        # Create some keys
        APIKey.objects.create(
            name='Key 1',
            org_id=self.org.id,
            token_hash='hash1'
        )
        APIKey.objects.create(
            name='Key 2',
            org_id=self.org.id,
            token_hash='hash2'
        )
        
        url = reverse('api-key-list')
        self.client.credentials(HTTP_X_ORG_ID=str(self.org.id))
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should list keys
        keys = response.data if isinstance(response.data, list) else response.data.get('results', [])
        self.assertGreaterEqual(len(keys), 2)
    
    def test_revoke_api_key(self):
        """Test revoking an API key"""
        api_key = APIKey.objects.create(
            name='Key to Revoke',
            org_id=self.org.id,
            token_hash='revokethis'
        )
        
        url = reverse('api-key-detail', kwargs={'pk': api_key.id})
        self.client.credentials(HTTP_X_ORG_ID=str(self.org.id))
        response = self.client.delete(url)
        
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        
        # Key should be inactive
        api_key.refresh_from_db()
        self.assertFalse(api_key.is_active)
    
    def test_rotate_api_key(self):
        """Test rotating an API key"""
        api_key = APIKey.objects.create(
            name='Key to Rotate',
            org_id=self.org.id,
            token_hash='rotatethis'
        )
        
        url = reverse('api-key-rotate', kwargs={'pk': api_key.id})
        self.client.credentials(HTTP_X_ORG_ID=str(self.org.id))
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)  # New token returned
    
    def test_cannot_access_other_org_keys(self):
        """Test that users cannot access other orgs' API keys"""
        # Create another org and key
        other_org = Organization.objects.create(name="Other Org", slug="other")
        other_key = APIKey.objects.create(
            name='Other Org Key',
            org_id=other_org.id,
            token_hash='otherhash'
        )
        
        url = reverse('api-key-detail', kwargs={'pk': other_key.id})
        # Use credentials of current user's org
        self.client.credentials(HTTP_X_ORG_ID=str(self.org.id))
        response = self.client.get(url)
        
        # Should be Not Found (queryset filtering)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class EmailUpdateTests(AuthTestCase):
    """Tests for email update flow"""
    
    def test_request_email_update(self):
        """Test requesting an email update"""
        url = reverse('update-email')
        payload = {
            'new_email': 'newemail@example.com',
            'password': 'TestPassword123!'
        }
        
        with patch('apps.auth.views.AuthenticationService') as mock_service:
            response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should send verification email
    
    def test_request_email_update_wrong_password(self):
        """Test email update with wrong password"""
        url = reverse('update-email')
        payload = {
            'new_email': 'newemail@example.com',
            'password': 'WrongPassword!'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    
    def test_request_email_update_existing_email(self):
        """Test email update to existing email"""
        # Create another user with target email
        User.objects.create_user(
            username='existinguser',
            email='existing@example.com',
            password='Pass123!'
        )
        
        url = reverse('update-email')
        payload = {
            'new_email': 'existing@example.com',
            'password': 'TestPassword123!'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class UserPreferencesTests(AuthTestCase):
    """Tests for user preferences endpoint"""
    
    def test_get_preferences(self):
        """Test getting user preferences"""
        url = reverse('user-preferences')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('theme', response.data)
    
    def test_update_preferences(self):
        """Test updating user preferences"""
        url = reverse('user-preferences')
        payload = {
            'preferences': {
                'theme': 'dark',
                'notifications': True,
                'language': 'en'
            }
        }
        
        response = self.client.patch(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class UserProfileTests(AuthTestCase):
    """Tests for user profile endpoints"""
    
    def test_get_profile(self):
        """Test getting user profile"""
        url = reverse('auth-user-profile')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(str(response.data['id']), str(self.user.id))
    
    def test_update_profile(self):
        """Test updating user profile"""
        url = reverse('update-profile')
        payload = {
            'first_name': 'Updated',
            'last_name': 'Name'
        }
        
        response = self.client.patch(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Updated')


class FeedbackAndSupportTests(AuthTestCase):
    """Tests for feedback and support endpoints"""
    
    def test_submit_feedback(self):
        """Test submitting feedback"""
        url = reverse('submit-feedback')
        payload = {
            'type': 'suggestion',
            'comments': 'Great product!',
            'rating': 'excellent'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
    
    def test_submit_support_request(self):
        """Test submitting support request"""
        url = reverse('support-request-list')
        payload = {
            'category': 'technical',
            'subject': 'Need help',
            'description': 'I need assistance with...',
            'priority': 'medium'
        }
        
        response = self.client.post(url, payload, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
