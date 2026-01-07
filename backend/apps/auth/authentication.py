import hashlib
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import APIKey


class APIKeyAuthentication(BaseAuthentication):
    """API Key authentication for organization-scoped access"""
    
    def authenticate(self, request):
        api_key = self.get_api_key(request)
        if not api_key:
            return None
        
        try:
            api_key_obj = self.validate_api_key(api_key)
            if not api_key_obj:
                return None
            
            # Set organization context on request
            request.org_id = str(api_key_obj.org_id)
            request.api_key = api_key_obj
            
            # Return a tuple of (user, auth) - user can be None for API key auth
            return (None, api_key_obj)
            
        except Exception as e:
            raise AuthenticationFailed('Invalid API key')
    
    def get_api_key(self, request):
        """Extract API key from request headers"""
        # Check X-API-Key header
        api_key = request.META.get('HTTP_X_API_KEY')
        if api_key:
            return api_key
        
        # Check Authorization header with Bearer prefix
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:]  # Remove 'Bearer ' prefix
        
        return None
    
    def validate_api_key(self, api_key):
        """Validate API key and return the APIKey object"""
        if not api_key:
            return None
        
        # Hash the provided key
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        try:
            api_key_obj = APIKey.objects.get(
                token_hash=key_hash,
                is_active=True
            )
            
            # Update last used timestamp
            from django.utils import timezone
            api_key_obj.last_used_at = timezone.now()
            api_key_obj.save(update_fields=['last_used_at'])
            
            return api_key_obj
            
        except APIKey.DoesNotExist:
            return None
