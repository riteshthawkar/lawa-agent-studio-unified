"""
Django signals for indexing app
"""
import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import IndexingJob
from apps.sites.models import Site

logger = logging.getLogger(__name__)


@receiver(post_save, sender=IndexingJob)
def update_site_last_indexed(sender, instance, created, **kwargs):
    """
    Update site's last_indexed_at when an indexing job completes successfully
    """
    # Only update when job status changes to completed
    if instance.status == 'completed' and instance.completed_at:
        try:
            # Get the site and update last_indexed_at
            site = Site.objects.get(id=instance.site_id)
            site.last_indexed_at = instance.completed_at
            site.save(update_fields=['last_indexed_at'])
            
            logger.info(
                "Updated site last_indexed_at",
                extra={
                    'site_id': str(instance.site_id),
                    'domain': site.domain,
                    'last_indexed_at': str(instance.completed_at),
                }
            )
        except Site.DoesNotExist:
            logger.warning(
                "Site not found for indexing job",
                extra={'site_id': str(instance.site_id)}
            )
        except Exception as e:
            logger.error(
                "Error updating site last_indexed_at",
                extra={'site_id': str(instance.site_id), 'error': str(e)},
                exc_info=True
            )

