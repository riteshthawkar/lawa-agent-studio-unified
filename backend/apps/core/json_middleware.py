import json
import logging
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

class JSONParsingMiddleware(MiddlewareMixin):
    """
    Middleware to safely check JSON body integrity before standard processing.
    This prevents 500 Internal Server Errors when DRF/Django encounters malformed JSON
    but expects valid input due to Content-Type header.
    """
    
    def process_request(self, request):
        if request.content_type == 'application/json':
            try:
                if request.body:
                    json.loads(request.body)
            except json.JSONDecodeError as e:
                logger.warning(f"Malformed JSON in request: {e}")
                return JsonResponse(
                    {'error': 'Invalid JSON format', 'detail': str(e)}, 
                    status=400
                )
        return None
