from django.test import SimpleTestCase, RequestFactory
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, APIException
from apps.core.exceptions import custom_exception_handler
from apps.core.organization_permissions import OrganizationAccessError, ResourceNotInOrganizationError

class MockView(APIView):
    def get(self, request):
        if request.GET.get('error') == 'permission':
            raise OrganizationAccessError("Access denied test")
        if request.GET.get('error') == 'resource':
            raise ResourceNotInOrganizationError("Resource not found test")
        if request.GET.get('error') == 'system':
            raise Exception("Unexpected system failure")
        if request.GET.get('error') == 'api':
            raise APIException("Generic API error")
        return Response({'status': 'ok'})

class StandardizedErrorTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.view = MockView.as_view()

    def test_permission_denied_format(self):
        request = self.factory.get('/test/?error=permission')
        response = self.view(request)
        
        # We need to manually invoke the exception handler because APIView.as_view() 
        # usually does this but we want to verify OUR handler specifically,
        # and SimpleTestCase doesn't set up the full Django middleware/DRF settings 
        # that automatically plug in the EXCEPTION_HANDLER.
        # However, DRF's APIView.handle_exception uses settings.EXCEPTION_HANDLER.
        # We can simulate the handler call or configure settings.
        
        # Better: Unit test the handler code directly.
        pass

    def test_handler_permission_error(self):
        exc = OrganizationAccessError("Access denied test")
        context = {'request': None}
        response = custom_exception_handler(exc, context)
        
        self.assertEqual(response.status_code, 403)
        self.assertIn('error', response.data)
        self.assertEqual(response.data['error']['code'], 'organization_access_denied')
        # DRF PermissionDenied detail is used
        self.assertIn('Access denied test', response.data['error']['message'])

    def test_handler_system_error(self):
        exc = Exception("Unexpected failure")
        context = {'request': None}
        response = custom_exception_handler(exc, context)
        
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data['error']['code'], 'internal_server_error')
        self.assertEqual(response.data['error']['message'], 'An unexpected system error occurred. Please try again later.')
        # Ensure internal details are NOT leaked
        self.assertNotIn('Unexpected failure', str(response.data))

    def test_handler_resource_not_in_org(self):
        exc = ResourceNotInOrganizationError("Resource error")
        context = {'request': None}
        response = custom_exception_handler(exc, context)
        
        self.assertEqual(response.status_code, 403)
        self.assertIn('Resource error', response.data['error']['message'])
