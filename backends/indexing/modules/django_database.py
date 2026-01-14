#!/usr/bin/env python3
"""
Django ORM Database Manager for Indexing Backend
Replaces SQLAlchemy with Django ORM for unified data access.
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from django.utils import timezone
from django.db import transaction, close_old_connections, connection
from django.db.models import Q, Count, Sum
from asgiref.sync import sync_to_async

# Import Django models
from django_setup import get_django_models

# Get models
models = get_django_models()
IndexingJob = models['IndexingJob']
Site = models['Site']
IndexedPage = models.get('IndexedPage')  # May not exist in older migrations

# Configure logging
logger = logging.getLogger(__name__)


def ensure_db_connection():
    """Ensure database connection is fresh before each query.
    
    This is critical for long-running async processes where connections
    can time out or be closed by the database server.
    """
    close_old_connections()
    # Ensure connection is usable
    try:
        connection.ensure_connection()
    except Exception as e:
        logger.warning(f"Connection ensure failed, will retry: {e}")
        close_old_connections()


class DjangoDatabaseManager:
    """Database manager using Django ORM for unified data access."""
    
    def __init__(self):
        """Initialize Django database manager."""
        self.logger = logger
        try:
            self.models = get_django_models()
            self.IndexingJob = self.models['IndexingJob']
            self.Site = self.models['Site']
            logger.info("Django ORM database manager initialized with models")
        except Exception as e:
            logger.error(f"Error getting Django models: {e}")
            # Direct import fallback
            try:
                from apps.indexing.models import IndexingJob
                from apps.sites.models import Site
                self.IndexingJob = IndexingJob
                self.Site = Site
                logger.info("Django ORM database manager initialized with direct imports")
            except Exception as direct_e:
                logger.error(f"Failed to import models directly: {direct_e}")
                raise
    
    async def _find_site_by_id_or_domain(self, identifier: Any) -> Optional[Any]:
        """
        Robustly find a Site by UUID string, exact domain, or loose domain match.
        Handles cases where 'identifier' might be a URL (with protocol) but DB has bare domain.
        """
        import uuid as uuid_module
        
        # 1. Try treating as UUID
        if isinstance(identifier, uuid_module.UUID):
            return await self.Site.objects.filter(id=identifier).afirst()
            
        identifier_str = str(identifier).strip()
        
        try:
            uuid_val = uuid_module.UUID(identifier_str)
            site = await self.Site.objects.filter(id=uuid_val).afirst()
            if site:
                return site
        except ValueError:
            pass
            
        # 2. Extract potential domain (strip protocol)
        domain_candidate = identifier_str
        if '://' in domain_candidate:
            domain_candidate = domain_candidate.split('://', 1)[1]
        if domain_candidate.endswith('/'):
            domain_candidate = domain_candidate[:-1]
            
        # 3. Exact Domain Match (try both original and stripped)
        site = await self.Site.objects.filter(domain__iexact=identifier_str).afirst()
        if site: return site
        
        site = await self.Site.objects.filter(domain__iexact=domain_candidate).afirst()
        if site: return site
        
        # 4. Containment Match (DB domain inside request URL, or request domain inside DB domain)
        # Check if DB domain is contained in the request URL/Domain (most likely for "https://foo.com" vs "foo.com")
        site = await self.Site.objects.filter(domain__icontains=domain_candidate).afirst()
        if site: return site
        
        # Check reverse: if the request identifier contains the stored domain
        # Warning: This might be ambiguous if multiple sites share substrings, but useful fallback
        # e.g. identifier="https://api.foo.com", DB="foo.com"
        # We can't easily query "identifier contains DB field" efficiently in all SQL safely in one go universally
        # So we rely on the above attempts first.
        
        return None

    async def create_task(self, task_data: Dict[str, Any]) -> str:
        """Create a new indexing task using Django Async ORM."""
        try:
            # Ensure fresh DB connection
            await sync_to_async(ensure_db_connection)()
            logger.info(f"Creating task with data: {task_data}")
            
            # Use robust lookup
            site_identifier = task_data.get("site_id")
            site = await self._find_site_by_id_or_domain(site_identifier)
            
            if site:
                site_id = site.id
            else:
                # Auto-create site logic (fallback)
                domain_to_search = str(site_identifier)
                if not domain_to_search.startswith(('http://', 'https://')):
                    domain_to_search = f'https://{domain_to_search}'
                    
                logger.info(f"Auto-creating site for domain: {domain_to_search}")
                try:
                    site = await self.Site.objects.acreate(
                        domain=domain_to_search,
                        status='active'
                    )
                    site_id = site.id
                except Exception as e:
                    logger.error(f"Failed to auto-create site: {e}")
                    raise ValueError(f"Could not create or find site for identifier: {site_identifier}")

            # Generate external_job_id if not provided
            external_job_id = task_data.get("external_job_id")
            if not external_job_id:
                external_job_id = f"auto_{task_data['task_id']}"
            
            # Use native acreate
            try:
                job = await self.IndexingJob.objects.acreate(
                    site_id=site_id,
                    external_job_id=external_job_id,
                    url=task_data["url"],
                    max_pages=task_data.get("max_pages", 100),
                    status="queued",
                    task_id=task_data["task_id"],
                    target_namespace=task_data.get("target_namespace", ""),  # CRITICAL: Preserve namespace for retrieval
                    error_message="",
                    urls_collected=0,
                    urls_processed=0,
                    documents_indexed=0,
                    pages_indexed=0,  # Initialize
                    created_at=timezone.now(),
                    updated_at=timezone.now()
                )
                logger.info(f"Created task {job.task_id} in Django database")
                return job.task_id
                
            except Exception as e:
                # Handle duplicate key errors
                if "duplicate key" in str(e) and task_data.get("external_job_id"):
                    existing_job = await self.IndexingJob.objects.filter(
                        external_job_id=task_data.get("external_job_id")
                    ).order_by('-created_at').afirst()
                    
                    if existing_job:
                        logger.info(f"Returning existing task {existing_job.task_id}")
                        return existing_job.task_id
                raise
                
        except Exception as e:
            logger.error(f"Error creating task with Django Async ORM: {e}")
            raise
    
    async def update_task_id(self, external_job_id: str, new_task_id: str) -> bool:
        """Update task_id for an existing job."""
        try:
            await sync_to_async(ensure_db_connection)()
            count = await self.IndexingJob.objects.filter(external_job_id=external_job_id).aupdate(task_id=new_task_id)
            return count > 0
        except Exception as e:
            logger.error(f"Error updating task_id: {e}")
            return False

    async def claim_and_start_task(self, task_id: str, external_job_id: Optional[str], start_time: datetime) -> bool:
        """Claim a task and mark as processing."""
        try:
            await sync_to_async(ensure_db_connection)()
            
            job = None
            if external_job_id:
                job = await self.IndexingJob.objects.filter(external_job_id=external_job_id).order_by('-created_at').afirst()
            
            if not job:
                job = await self.IndexingJob.objects.filter(task_id=task_id).afirst()
            
            if not job:
                return False
            
            job.task_id = task_id
            job.status = 'processing'
            job.started_at = timezone.make_aware(start_time) if start_time.tzinfo is None else start_time
            job.updated_at = timezone.now()
            await job.asave()
            
            # Update Site status
            site = await self.Site.objects.filter(id=job.site_id).afirst()
            if site and site.status != 'indexing':
                site.status = 'indexing'
                await site.asave(update_fields=['status'])

            return True
        except Exception as e:
            logger.error(f"Error claiming task: {e}")
            return False

    def _sanitize_for_json(self, value: Any) -> Any:
        """Sanitize a value to ensure it's JSON serializable."""
        if value is None: return None
        if isinstance(value, (str, int, float, bool)): return value
        if isinstance(value, dict):
            return {k: self._sanitize_for_json(v) for k, v in value.items()
                    if k not in ('results', 'crawl_results')}
        if isinstance(value, (list, tuple)):
            return [self._sanitize_for_json(item) for item in value]
        try:
            import json
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return str(value) if value else None

    async def update_task_status(self, task_id: str, status: str, **kwargs) -> bool:
        """Update task status and optional fields using Django Async ORM."""
        await sync_to_async(ensure_db_connection)()

        async def _update_job():
            update_fields = {'status': status, 'updated_at': timezone.now()}

            for field, value in kwargs.items():
                if hasattr(IndexingJob, field):
                    if isinstance(value, datetime) and value.tzinfo is None:
                        value = timezone.make_aware(value)
                    if field == 'error_message' and value is None:
                        value = ''
                    if field in ('phase1_result', 'phase2_result', 'result'):
                        value = self._sanitize_for_json(value)
                    update_fields[field] = value
            
            try:
                job = await self.IndexingJob.objects.filter(task_id=task_id).afirst()
                if not job:
                    return False

                for k, v in update_fields.items():
                    setattr(job, k, v)
                await job.asave()
                
                site = await self.Site.objects.filter(id=job.site_id).afirst()
                if site:
                    if status in ['processing', 'collecting_urls', 'processing_urls']:
                        if site.status != 'indexing':
                            site.status = 'indexing'
                            await site.asave(update_fields=['status'])
                    elif status == 'completed':
                        site.status = 'active'
                        site.last_indexed_at = timezone.now()

                        # CRITICAL FIX: Update active_namespace from job.target_namespace
                        # This ensures the widget can find vectors even if webhook fails
                        if job.target_namespace:
                            site.active_namespace = job.target_namespace
                            logger.info(f"Setting site {site.id} active_namespace to {job.target_namespace}")

                        # Store IndexedPage records from phase2_result.url_results
                        phase2 = update_fields.get('phase2_result') or {}
                        url_results = phase2.get('url_results', []) if isinstance(phase2, dict) else []
                        if url_results:
                            await self._store_indexed_pages_async(job, url_results)

                        # Refresh site stats after storing pages
                        if IndexedPage:
                            count = await IndexedPage.objects.filter(site_id=site.id, status='indexed').acount()
                            site.indexed_pages_count = count

                            total_docs = await IndexedPage.objects.filter(site_id=site.id, status='indexed').aaggregate(total=Sum('document_count'))
                            site.total_documents = total_docs.get('total') or count

                        # Include active_namespace in update_fields
                        site_update_fields = ['status', 'last_indexed_at', 'indexed_pages_count', 'total_documents']
                        if job.target_namespace:
                            site_update_fields.append('active_namespace')
                        await site.asave(update_fields=site_update_fields)

                    elif status in ['failed', 'cancelled']:
                        site.status = 'active' 
                        await site.asave(update_fields=['status'])
                
                return True
            except Exception as e:
                logger.error(f"Error in _update_job: {e}")
                return False
        
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                success = await _update_job()
                if success:
                    logger.info(f"Updated task {task_id} status to {status}")
                else:
                    logger.warning(f"No task found with task_id {task_id}")
                return success
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                is_transient = any(x in error_str for x in ['connection', 'timeout', 'deadlock', 'locked'])
                
                if is_transient and attempt < max_retries - 1:
                    logger.warning(f"Transient DB error (attempt {attempt + 1}/{max_retries}): {e}")
                    await asyncio.sleep(0.5 * (2 ** attempt))  # Exponential backoff
                    continue
                else:
                    logger.error(f"Error updating task status with Django ORM: {e}")
                    # Don't crash - return False so processing can continue
                    return False
        
        logger.error(f"All {max_retries} attempts failed for task status update: {last_error}")
        return False
    
    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task by task_id using Django ORM."""
        
        @sync_to_async
        def _get_job():
            try:
                ensure_db_connection()
                job = self.IndexingJob.objects.filter(task_id=task_id).first()
                return self._job_to_dict(job) if job else None
            except Exception as e:
                logger.error(f"Error getting task: {e}")
                return None
        
        return await _get_job()
    
    async def get_task_by_external_job(self, external_job_id: str) -> Optional[Dict[str, Any]]:
        """Get task by external_job_id using Django ORM."""
        
        @sync_to_async
        def _get_job():
            try:
                ensure_db_connection()
                job = self.IndexingJob.objects.filter(
                    external_job_id=external_job_id
                ).order_by('-created_at').first()
                return self._job_to_dict(job) if job else None
            except Exception as e:
                logger.error(f"Error getting task by external job ID: {e}")
                return None
        
        return await _get_job()
    
    async def list_tasks(self, status_filter: Optional[str] = None, 
                        site_id: Optional[str] = None, 
                        external_job_id: Optional[str] = None, 
                        limit: int = 100) -> List[Dict[str, Any]]:
        """List tasks with optional filters using Django ORM."""
        
        @sync_to_async
        def _list_jobs():
            try:
                # Build query
                queryset = self.IndexingJob.objects.all()
                
                # Apply filters
                if status_filter:
                    queryset = queryset.filter(status=status_filter)
                if site_id:
                    queryset = queryset.filter(site_id=site_id)
                if external_job_id:
                    queryset = queryset.filter(external_job_id=external_job_id)
                
                # Order by creation date and limit
                jobs = list(queryset.order_by('-created_at')[:limit])
                
                return [self._job_to_dict(job) for job in jobs]
            except Exception as e:
                logger.error(f"Error listing tasks: {e}")
                return []
        
        return await _list_jobs()
    
    def _job_to_dict(self, job: IndexingJob) -> Dict[str, Any]:
        """Convert Django IndexingJob model to dictionary."""
        # Calculate progress percentage
        progress_percentage = 0
        if job.status == 'collecting_urls':
            progress_percentage = 25
        elif job.status == 'processing_urls':
            # Between 25-75% based on URLs processed
            if job.urls_collected > 0:
                progress_percentage = 25 + int((job.urls_processed / job.urls_collected) * 50)
            else:
                progress_percentage = 50
        elif job.status == 'completed':
            progress_percentage = 100
        elif job.status in ['failed', 'cancelled']:
            progress_percentage = 0
        else:
            progress_percentage = 10
        
        return {
            'id': str(job.id),
            'task_id': job.task_id or '',
            'site_id': str(job.site_id),
            'external_job_id': job.external_job_id or '',
            'url': job.url,
            'max_pages': job.max_pages,
            'status': job.status,
            'error_message': job.error_message or '',
            'urls_collected': job.urls_collected,
            'urls_processed': job.urls_processed,
            'documents_indexed': job.documents_indexed,
            'pages_indexed': getattr(job, 'pages_indexed', 0), # Added
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            'created_at': job.created_at.isoformat() if job.created_at else None,
            'updated_at': job.updated_at.isoformat() if job.updated_at else None,
            # Bug #6 fix: Include callback_url for retries
            'callback_url': getattr(job, 'callback_url', None) or '',
            # Bug #10 fix: Include phase results if available
            'phase1_result': getattr(job, 'phase1_result', None),
            'phase2_result': getattr(job, 'phase2_result', None),
            'target_namespace': getattr(job, 'target_namespace', None) or '',
            # Add progress object for frontend compatibility
            'progress': {
                'urls_collected': job.urls_collected,
                'urls_processed': job.urls_processed,
                'documents_indexed': job.documents_indexed,
                'progress_percentage': progress_percentage
            }
        }
    
    async def _store_indexed_pages_async(self, job, url_results: List[Dict[str, Any]]) -> int:
        """
        Store IndexedPage records from url_results using Async ORM.
        
        Args:
            job: The IndexingJob that produced these results
            url_results: List of URL result dictionaries from iterative_processor

        Returns:
            Number of IndexedPage records stored
        """
        if not IndexedPage:
            logger.warning("IndexedPage model not available, skipping page storage")
            return 0

        if not url_results:
            return 0

        import hashlib

        logger.info(f"Storing {len(url_results)} indexed pages for job {job.id}")
        stored_count = 0

        for url_result in url_results:
            try:
                url = url_result.get('url', '')
                if not url:
                    continue

                # Generate URL hash for uniqueness constraint
                url_hash = hashlib.sha256(url.encode()).hexdigest()

                # Map status
                status = url_result.get('status', 'indexed')
                status_map = {
                    'indexed': 'indexed',
                    'failed': 'failed',
                    'skipped': 'skipped',
                }
                page_status = status_map.get(status, 'indexed')

                # Use aupdate_or_create for upsert behavior
                now = timezone.now()
                page, created = await IndexedPage.objects.aupdate_or_create(
                    site_id=job.site_id,
                    url_hash=url_hash,
                    defaults={
                        'url': url,
                        'indexing_job_id': job.id,
                        'org_id': job.org_id,
                        'title': url_result.get('title', '')[:500] if url_result.get('title') else '',
                        'content_type': url_result.get('content_type', 'html'),
                        'status': page_status,
                        'document_count': url_result.get('document_count', 0),
                        'content_size_bytes': url_result.get('content_size_bytes', 0),
                        'error_message': url_result.get('error_message', '')[:1000] if url_result.get('error_message') else '',
                        'processed_at': now,
                    }
                )
                
                # Check discovered_at separately
                if created or not page.discovered_at:
                    page.discovered_at = now
                    await page.asave(update_fields=['discovered_at'])
                stored_count += 1

            except Exception as e:
                logger.warning(f"Failed to store indexed page for {url_result.get('url', 'unknown')}: {e}")
                continue

        logger.info(f"Stored {stored_count}/{len(url_results)} indexed pages for job {job.id}")
        return stored_count

    async def get_task_stats(self) -> Dict[str, Any]:
        """Get task statistics for health and stats endpoints."""

        @sync_to_async
        def _get_stats():
            try:
                # Get total count
                total_tasks = self.IndexingJob.objects.count()

                # Get counts by status
                status_choices = [
                    'queued', 'processing', 'collecting_urls',
                    'processing_urls', 'running', 'completed', 'failed', 'cancelled'
                ]
                by_status = {}
                for status_choice in status_choices:
                    by_status[status_choice] = self.IndexingJob.objects.filter(
                        status=status_choice
                    ).count()

                # Calculate active and completed counts
                active_statuses = ['queued', 'processing', 'collecting_urls', 'processing_urls', 'running']
                active_tasks = sum(by_status.get(s, 0) for s in active_statuses)
                completed_tasks = by_status.get('completed', 0)
                failed_tasks = by_status.get('failed', 0)

                # Calculate success rate
                total_finished = completed_tasks + failed_tasks
                success_rate = (completed_tasks / total_finished * 100) if total_finished > 0 else 0

                return {
                    'total_tasks': total_tasks,
                    'active_tasks': active_tasks,
                    'completed_tasks': completed_tasks,
                    'failed_tasks': failed_tasks,
                    'success_rate': round(success_rate, 1),
                    'by_status': by_status
                }
            except Exception as e:
                logger.error(f"Error getting task stats: {e}")
                return {
                    'total_tasks': 0,
                    'active_tasks': 0,
                    'completed_tasks': 0,
                    'failed_tasks': 0,
                    'success_rate': 0,
                    'by_status': {}
                }

        return await _get_stats()

    async def get_excluded_patterns(self, site_id: str) -> List[Dict[str, Any]]:
        """
        P2.3: Get active excluded URL patterns for a site.
        """
        try:
            site = await self._find_site_by_id_or_domain(site_id)
            if not site:
                return []
                
            patterns = []
            # Note: models['ExcludedURLPattern'] is likely not populated in __init__ if it wasn't in get_django_models
            # Let's import safely inside
            from django.apps import apps
            ExcludedURLPattern = apps.get_model('sites', 'ExcludedURLPattern')
            
            async for p in ExcludedURLPattern.objects.filter(site_id=site.id, is_active=True):
                 patterns.append({
                    'id': str(p.id),
                    'pattern': p.pattern,
                    'pattern_type': p.pattern_type,
                    'description': p.description,
                })
            return patterns
        except Exception as e:
            logger.error(f"Error fetching excluded patterns: {e}")
            return []


    def url_matches_exclusion(self, url: str, patterns: List[Dict[str, Any]]) -> bool:
        """
        Check if a URL matches any exclusion pattern.
        
        Args:
            url: URL to check
            patterns: List of pattern dictionaries
            
        Returns:
            True if URL should be excluded
        """
        import re
        
        for p in patterns:
            pattern = p['pattern']
            pattern_type = p['pattern_type']
            
            try:
                if pattern_type == 'exact':
                    if url == pattern:
                        return True
                elif pattern_type == 'prefix':
                    if url.startswith(pattern):
                        return True
                elif pattern_type == 'suffix':
                    if url.endswith(pattern):
                        return True
                elif pattern_type == 'contains':
                    if pattern in url:
                        return True
                elif pattern_type == 'glob':
                    import fnmatch
                    if fnmatch.fnmatch(url, pattern):
                        return True
                elif pattern_type == 'regex':
                    if re.match(pattern, url):
                        return True
            except Exception:
                continue
        
        return False

    async def get_user_added_urls(self, site_id: str) -> List[str]:
        """
        P2.2: Get URLs that were manually added by users.
        These should be included in re-indexing runs.
        
        Args:
            site_id: UUID of the site
            
        Returns:
            List of user-added URLs
        """
        @sync_to_async
        def _get_urls():
            try:
                from apps.indexing.models import IndexedPage
                import uuid as uuid_module
                
                # Convert site_id to UUID if string
                if isinstance(site_id, str):
                    try:
                        site_uuid = uuid_module.UUID(site_id)
                    except ValueError:
                        site = self.Site.objects.filter(domain__icontains=site_id).first()
                        if site:
                            site_uuid = site.id
                        else:
                            return []
                else:
                    site_uuid = site_id
                
                pages = IndexedPage.objects.filter(
                    site_id=site_uuid,
                    user_added=True
                ).values_list('url', flat=True)
                
                return list(pages)
            except Exception as e:
                logger.error(f"Error fetching user-added URLs: {e}")
                return []
        
        return await _get_urls()

    async def initialize(self):
        """Initialize database (Django handles migrations)."""
        logger.info("Django ORM database manager initialized - using Django migrations")
        return True
    
    async def close(self):
        """Close database connections (Django handles this)."""
        logger.info("Django ORM database manager closed")
        return True

# Global database manager instance
db_manager = DjangoDatabaseManager()