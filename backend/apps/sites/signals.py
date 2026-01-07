import logging
from django.db.models.signals import post_delete
from django.dispatch import receiver
from .models import Site
from apps.indexing.services import IndexingService

logger = logging.getLogger(__name__)

@receiver(post_delete, sender=Site)
def cleanup_site_vectors(sender, instance, **kwargs):
    """
    Cleanup Pinecone namespace when a site is deleted.
    This ensures we don't leave orphan data in the vector database.
    """
    try:
        namespace = instance.get_namespace()
        logger.info(f"Site {instance.id} deleted. Cleaning up namespace: {namespace}")
        
        service = IndexingService()
        # Fire and forget - logs errors internally but doesn't stop deletion
        service.delete_namespace(namespace)
        
    except Exception as e:
        logger.error(f"Error in cleanup_site_vectors signal: {e}")
