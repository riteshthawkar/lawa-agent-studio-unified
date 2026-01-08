import hashlib
import requests
import logging
from django.conf import settings
from django.utils import timezone
from django.db import models
from .models import IndexingJob
from apps.sites.models import Site
from apps.usage.models import Quota, UsageEvent
from apps.core.exceptions import SiteNotVerified, QuotaExceeded


class IndexingServiceTimeout(Exception):
    """Raised when the external indexing service times out."""
    pass


class IndexingService:
    """Service for interacting with external indexing service"""
    
    def __init__(self):
        self.base_url = settings.INDEXING_API_BASE
        self.api_token = settings.INDEXING_API_TOKEN
        # Use shorter timeouts so we can fall back quickly and stay responsive
        self.timeout = (5, 20)  # (connect, read)
        self.logger = logging.getLogger(__name__)
        
        # Ensure base URL points to indexing service (normalize host)
        # 0.0.0.0 is a bind address, not a routable client target
        if self.base_url:
            self.base_url = self.base_url.replace('0.0.0.0', '127.0.0.1')
        
        # Default to configured base or fallback
        if not self.base_url:
             self.base_url = 'http://127.0.0.1:8080'
    
    def create_indexing_job(self, site, params, user_id, callback_url=None, append_mode=False):
        """
        Create a new indexing job.
        
        Args:
            site: The Site object to index
            params: Dictionary with 'url', 'max_pages', etc.
            user_id: ID of the user triggering the job
            callback_url: Optional callback URL for status updates
            append_mode: If True, uses existing active_namespace instead of creating new one.
                        This allows adding pages to an existing index (e.g., for undo exclusion).
        """
        
        self.logger.info(f"Creating indexing job for site {site.id} by user {user_id} (append_mode={append_mode})")

        # Validate params
        if not isinstance(params, dict):
            params = dict(params)
        else:
            params = {**params}

        # IDEMPOTENCY CHECK (Bug #30 fix):
        # If external_job_id is provided, check if it already exists
        external_job_id = params.get('external_job_id')
        if external_job_id:
            try:
                existing_job = IndexingJob.objects.filter(external_job_id=external_job_id).first()
                if existing_job:
                    self.logger.info(f"Idempotent request: Job {external_job_id} already exists ({existing_job.status})")
                    # If existing job is completed or active, return it
                    return existing_job
            except Exception as e:
                self.logger.warning(f"Error checking idempotency: {e}")

        # Generate idempotent job ID if not provided or new
        job_id = external_job_id or self._generate_job_id(site, params)
        self.logger.debug(f"Using job ID: {job_id}")

        # Get organization ID for quota enforcement
        org_id = getattr(site, 'org_id', None)

        # MVP: Allow multiple indexing attempts for the same site
        # Each attempt gets a unique job_id with timestamp
        request_url = params.get('url', site.domain)
        requested_max_pages = params.get('max_pages', 100)

        # QUOTA ENFORCEMENT: Clamp max_pages to organization's tier limit
        max_pages = self._enforce_page_limit(org_id, requested_max_pages)
        if max_pages != requested_max_pages:
            self.logger.info(f"Clamped max_pages from {requested_max_pages} to {max_pages} based on org {org_id} quota")
            # Update params so the clamped value is used downstream
            params['max_pages'] = max_pages

        # Determine target namespace
        if append_mode and site.active_namespace:
            # Use existing namespace - append vectors to current index
            target_namespace = site.active_namespace
            self.logger.info(f"Append mode: using existing namespace {target_namespace}")
        else:
            # Create new namespace (default behavior for full re-index)
            timestamp_suffix = int(timezone.now().timestamp())
            target_namespace = f"site_{site.id}_{timestamp_suffix}"
            
        # Build callback URL for the job (Bug #6 fix - persist for retries)
        if callback_url is None:
            callback_url = self._build_callback_url()

        # Race Condition Fix: Handle IntegrityError if job was created concurrently
        try:
            job = IndexingJob.objects.create(
                site_id=site.id,
                org_id=getattr(site, 'org_id', None),
                external_job_id=job_id,
                url=request_url,
                max_pages=max_pages,
                target_namespace=target_namespace,
                callback_url=callback_url  # Store for retries
            )
        except Exception as e:
            # Check for unique constraint violation (IntegrityError)
            # We catch generic Exception and check string because importing IntegrityError 
            # might be cleaner but this catches all DB unique violations.
            if "unique constraint" in str(e).lower() or "integrityerror" in str(e).lower():
                self.logger.info(f"Race condition caught: Job {job_id} created concurrently. Returning existing job.")
                existing_job = IndexingJob.objects.filter(external_job_id=job_id).first()
                if existing_job:
                    return existing_job
            # If it was a real error, re-raise
            raise e
        
        # Call external indexing service AFTER transaction commits
        # This prevents the "Job not found" race condition where the external service 
        # tries to update the job before the DB transaction has committed.
        def trigger_indexing_service():
            try:
                self.logger.info(f"Transaction committed. Triggering indexing service for job {job.id}")
                # Inject target namespace into params for the call
                call_params = params.copy()
                call_params['target_namespace'] = target_namespace
                
                # We don't strictly need the response here as the external service 
                # will update the job status asynchronously in the background.
                # However, we allow it to update the local object if possible for logging.
                response = self._call_indexing_service(site, call_params, job_id, user_id, callback_url)
                
                # The response handling here is a 'nice to have' for local logging context
                # passed back from the synchronous API call (if it returns one).
                # But the source of truth is now the DB record which the external service updates.
                task_id_resp = response.get('task_id', '')
                status_resp = response.get('status', 'queued')
                self.logger.info(f"Triggered indexing service. API returned task_id={task_id_resp}, status={status_resp}")

            except IndexingServiceTimeout as e:
                # Bug #11 fix: Update job status to 'processing' on timeout
                # The external service may still be processing, so don't mark as failed
                self.logger.warning(f"Indexing service timed out for job {job.id}: {str(e)}. Marking as processing.")
                try:
                    timeout_job = IndexingJob.objects.get(id=job.id)
                    if timeout_job.status == 'queued':
                        # Mark as processing since external service may still be working
                        timeout_job.status = 'processing'
                        timeout_job.started_at = timezone.now()
                        timeout_job.save(update_fields=['status', 'started_at'])
                        self.logger.info(f"Job {job.id} marked as processing after timeout")
                except Exception as inner_e:
                    self.logger.error(f"Could not update job {job.id} status after timeout: {inner_e}")
            except Exception as e:
                self.logger.error(f"Failed to call indexing service for job {job.id}: {str(e)}")
                # Since we are outside the original request view transaction here, 
                # we technically could update the job status to failed.
                try:
                    # Re-fetch job to ensure we have fresh state/lock if needed, though this is a new transaction context usually
                    failed_job = IndexingJob.objects.get(id=job.id)
                    failed_job.mark_failed(str(e))
                except Exception as inner_e:
                     self.logger.error(f"Could not mark job {job.id} as failed: {inner_e}")

        # Register the trigger to run only after the current transaction commits successsfully
        from django.db import transaction
        transaction.on_commit(trigger_indexing_service)
        
        self.logger.info(f"Queued indexing trigger for job {job.id} (waiting for transaction commit)")
        
        # Track usage
        from apps.usage.services import UsageTracker
        UsageTracker.track_event(
            org_id=job.org_id,
            event_type="index_write",
            units=1,
            site_id=site.id,
            meta={"max_pages": max_pages}
        )

        return job
    
    def _generate_job_id(self, site, params):
        """Generate unique job ID with timestamp for each indexing attempt"""
        # Include timestamp to ensure each indexing attempt gets a unique ID
        # This allows re-indexing the same site multiple times
        timestamp = int(timezone.now().timestamp())
        content = f"{site.id}:{site.domain}:{params.get('max_pages', 100)}:{timestamp}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _call_indexing_service(self, site, params, job_id, user_id, callback_url=None):
        """Call external indexing service with correct API payload structure"""
        url = f"{self.base_url}/index"
        
        # Build callback URL if not provided
        if callback_url is None:
            callback_url = self._build_callback_url()
        
        # Payload structure according to indexing backend API specification
        payload = {
            # Required fields - simplified for MVP
            'url': params.get('url', site.domain),
            'max_pages': params.get('max_pages', 100),
            'site_id': str(site.id),
            'external_job_id': job_id,
            'namespace_override': params.get('target_namespace'),  # Indexing service expects namespace_override
            'callback_url': callback_url,
            'embed_model': params.get('embed_model', getattr(settings, 'EMBED_MODEL', 'gemini-embedding-001')),
        }

        optional_keys = [
            'allowed_domains',
            'excluded_subdomains',
            'pinecone_index',
            'streaming_mode',
            'use_namespaces',
            'namespace_prefix',
            'custom_config',
        ]

        for key in optional_keys:
            if key in params and params.get(key) not in (None, ''):
                payload[key] = params.get(key)
        
        headers = {
            'Content-Type': 'application/json',
        }
        
        # Add auth token if configured
        if self.api_token:
            headers['Authorization'] = f'Bearer {self.api_token}'
        
        try:
            self.logger.info(f"Making request to {url} with payload: {payload}")
            self.logger.info(f"Base URL: {self.base_url}, Full URL: {url}")
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            self.logger.info(f"Successfully called indexing service, got task_id: {result.get('task_id')}")
            return result
        except requests.exceptions.ReadTimeout as e:
            # Fallback: attempt to fetch task by external_job_id to honor idempotency
            self.logger.warning(
                f"Indexing service timed out after {self.timeout}s, attempting idempotent lookup for external_job_id={job_id}"
            )
            try:
                lookup_url = f"{self.base_url}/tasks"
                query_params = {
                    "external_job_id": job_id,
                    "limit": 1,
                }
                # Remove None values from params
                query_params = {k: v for k, v in query_params.items() if v is not None}
                lookup_resp = requests.get(lookup_url, params=query_params, timeout=(5, 10))
                lookup_resp.raise_for_status()
                payload = lookup_resp.json()

                # Handle both legacy (active/completed) and new (results) structures
                results = payload.get("results", []) or []
                if results:
                    chosen = results[0]
                else:
                    active = payload.get("active_tasks", []) or []
                    completed = payload.get("completed_tasks", []) or []
                    chosen = (active[0] if len(active) > 0 else (completed[0] if len(completed) > 0 else None))
                if chosen:
                    self.logger.info(
                        f"Idempotent lookup succeeded; returning existing task_id={chosen.get('task_id')} status={chosen.get('status')}"
                    )
                    return {
                        "task_id": chosen.get("task_id", ""),
                        "status": chosen.get("status", "queued"),
                        "message": "Existing task returned after timeout"
                    }
            except requests.exceptions.RequestException as lookup_error:
                self.logger.warning(f"Idempotent lookup failed: {lookup_error}")
            # If lookup failed or no task found, surface the timeout
            self.logger.error(f"Request failed to indexing service due to timeout: {str(e)}")
            raise IndexingServiceTimeout(f"Indexing service timeout: {str(e)}")
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request failed to indexing service: {str(e)}")
            raise Exception(f"Failed to call indexing service: {str(e)}")
    
    def _build_callback_url(self):
        """Build webhook callback URL"""
        from django.urls import reverse
        from django.conf import settings
        
        # Build the webhook URL
        webhook_url = reverse('indexing-webhook')
        # Use dynamic base URL from settings or fallback to localhost
        base_url = getattr(settings, 'BACKEND_BASE_URL', 'http://localhost:8080')
        return f"{base_url}{webhook_url}"
    
    def update_job_status(self, job_id, status, phase1_result=None, phase2_result=None, error_message=None, progress_data=None, url_results=None):
        """Update job status from webhook with proper status handling"""
        try:
            job = IndexingJob.objects.get(external_job_id=job_id)
            
            # State Machine Guard: Prevent reverting from terminal states
            if job.status in ['completed', 'cancelled', 'failed']:
                self.logger.warning(f"Ignored status update to '{status}' for job {job.id} because it is already in terminal state '{job.status}'")
                return job

            self.logger.info(f"Updating job {job.id} status from {job.status} to {status}")

            # Handle different status transitions according to API spec
            if status == 'processing':
                job.mark_started()
            elif status == 'collecting_urls':
                job.mark_collecting_urls()
            elif status == 'processing_urls':
                job.mark_processing_urls()
            elif status == 'running':
                job.mark_running()
            elif status == 'completed':
                # Store phase results for diagnostics (Bug #10 fix)
                if phase1_result:
                    job.phase1_result = phase1_result
                if phase2_result:
                    job.phase2_result = phase2_result
                if phase1_result or phase2_result:
                    job.save(update_fields=[f for f in ['phase1_result', 'phase2_result']
                                            if getattr(job, f) is not None])

                job.mark_completed()
                self.logger.info(f"Job {job.id} completed successfully")

                # Bug #26 fix: Store per-URL results in IndexedPage model
                if url_results:
                    self._store_indexed_pages(job, url_results)

                # CRITICAL FIX: Preventive Cleanup for Race Condition
                # Before making this namespace active, ensure no excluded content slipped in.
                # This handles cases where a user added an exclusion pattern *while* the job was running.
                if job.target_namespace:
                    self._perform_preventive_cleanup(job)

                # Update Site statistics when indexing completes
                self._update_site_stats(job, progress_data)
            elif status == 'failed':
                job.mark_failed(error_message or 'Unknown error')
                self.logger.error(f"Job {job.id} failed: {error_message}")
            elif status == 'cancelled':
                job.mark_cancelled()
                self.logger.info(f"Job {job.id} was cancelled")

            # Update progress if provided
            if progress_data:
                job.update_progress(
                    urls_collected=progress_data.get('urls_collected'),
                    urls_processed=progress_data.get('urls_processed'),
                    documents_indexed=progress_data.get('documents_indexed')
                )
                self.logger.debug(f"Updated progress for job {job.id}: {progress_data}")

            return job

        except IndexingJob.DoesNotExist:
            self.logger.error(f"Indexing job {job_id} not found for status update")
            raise ValueError(f"Indexing job {job_id} not found")

    def _perform_preventive_cleanup(self, job):
        """
        Run cleanup for all active exclusion patterns on the new namespace 
        before it goes live. This handles race conditions.
        """
        from apps.sites.models import ExcludedURLPattern, Site
        
        try:
            site = Site.objects.get(id=job.site_id)
            patterns = ExcludedURLPattern.objects.filter(site_id=site.id, is_active=True)
            
            if not patterns.exists():
                return
                
            self.logger.info(f"Running preventive cleanup for {patterns.count()} patterns on new namespace '{job.target_namespace}'")
            
            # We reuse cleanup_excluded_vectors but we need to ensure it targets the NEW namespace.
            # cleanup_excluded_vectors uses IndexedPage -> IndexingJob mapping.
            # Since _store_indexed_pages has already run, the pages are linked to THIS job.
            # So cleanup_excluded_vectors will naturally find the correct namespace (job.target_namespace).
            
            total_cleaned = 0
            for pattern in patterns:
                result = self.cleanup_excluded_vectors(site, pattern)
                total_cleaned += result.get('deleted_count', 0)
                
            if total_cleaned > 0:
                self.logger.info(f"Preventive cleanup removed {total_cleaned} vectors from new namespace '{job.target_namespace}'")
                
        except Exception as e:
            self.logger.error(f"Failed to perform preventive cleanup for job {job.id}: {e}")

    def _delete_vectors_by_urls(self, namespace, urls):
        """
        Delete vectors from Pinecone for specific URLs using the indexing API.
        Now supports batching to avoid payload size limits.
        
        Args:
            namespace: Pinecone namespace
            urls: List of URLs whose vectors should be deleted
            
        Returns:
            int: Number of vectors deleted
        """
        if not urls:
            return 0
            
        # Batch size for deletions
        BATCH_SIZE = 1000
        total_deleted = 0
        
        # Split URLs into batches
        for i in range(0, len(urls), BATCH_SIZE):
            batch_urls = urls[i:i + BATCH_SIZE]
            
            # The indexing API doesn't have a direct delete endpoint yet,
            # so we use the Pinecone client directly via a new endpoint
            url = f"{self.base_url}/vectors/delete"
            
            payload = {
                'namespace': namespace,
                'urls': batch_urls
            }
            
            headers = {
                'Content-Type': 'application/json',
            }
            
            if self.api_token:
                headers['Authorization'] = f'Bearer {self.api_token}'
            
            try:
                self.logger.info(f"Deleting batch of {len(batch_urls)} vectors from {namespace}")
                response = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=60  # Longer timeout for deletion
                )
                
                if response.status_code == 404:
                    # Endpoint not available yet - log warning and return 0
                    self.logger.warning(f"Vector delete endpoint not available, cleanup skipped")
                    return total_deleted
                    
                response.raise_for_status()
                result = response.json()
                total_deleted += result.get('deleted_count', 0)
                
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Failed to delete vector batch: {str(e)}")
                # Continue with next batch instead of failing completely using 'continue'
                # but we are in a loop, so just log and continue
        
        return total_deleted

    def delete_indexed_page_vectors(self, site, url):
        """
        Delete all vectors for a specific indexed page URL.
        
        Called when a user manually deletes an indexed page.
        
        Args:
            site: Site object with the namespace
            url: URL of the page to delete vectors for
            
        Returns:
            int: Number of vectors deleted
        """
        # Try to find the specific job that indexed this page to get correct namespace
        from apps.indexing.models import IndexedPage, IndexingJob
        
        target_namespace = None
        try:
            # Find the most recent successful indexing of this URL for this site
            indexed_page = IndexedPage.objects.filter(
                site_id=site.id, 
                url=url,
                status='indexed'
            ).order_by('-created_at').first()
            
            if indexed_page:
                job = IndexingJob.objects.filter(id=indexed_page.indexing_job_id).first()
                if job and job.target_namespace:
                    target_namespace = job.target_namespace
                    self.logger.info(f"Found correct namespace '{target_namespace}' from job {job.id} for URL '{url}'")
        except Exception as e:
            self.logger.warning(f"Error resolving specific namespace for deletion: {e}")

        # Fallback to site's active namespace if we couldn't resolve it specifically
        if not target_namespace:
            target_namespace = site.get_namespace()
            self.logger.info(f"Using site active namespace '{target_namespace}' (fallback) for URL '{url}'")

        self.logger.info(f"Deleting vectors for URL '{url}' in namespace '{target_namespace}'")
        
        try:
            return self._delete_vectors_by_urls(target_namespace, [url])
        except Exception as e:
            self.logger.error(f"Failed to delete page vectors: {e}")
            return 0

    def _store_indexed_pages(self, job, url_results):
        """
        Bug #26 fix: Store per-URL results in IndexedPage model for visibility.

        Args:
            job: The IndexingJob that produced these results
            url_results: List of URL result dictionaries from the indexing service
        """
        from .models import IndexedPage
        from django.utils import timezone

        if not url_results:
            return

        self.logger.info(f"Storing {len(url_results)} indexed pages for job {job.id}")

        stored_count = 0
        for url_result in url_results:
            try:
                url = url_result.get('url', '')
                if not url:
                    continue

                # Map indexing service status to IndexedPage status
                status = url_result.get('status', 'indexed')
                status_map = {
                    'indexed': 'indexed',
                    'failed': 'failed',
                    'skipped': 'skipped',
                }
                page_status = status_map.get(status, 'indexed')

                # Use get_or_create_from_url for upsert behavior
                page, created = IndexedPage.get_or_create_from_url(
                    site_id=job.site_id,
                    indexing_job_id=job.id,
                    url=url,
                    org_id=job.org_id,
                    title=url_result.get('title', ''),
                    content_type=url_result.get('content_type', 'html'),
                    status=page_status,
                    document_count=url_result.get('document_count', 0),
                    content_size_bytes=url_result.get('content_size_bytes', 0),
                    error_message=url_result.get('error_message', ''),
                )

                # If this was an update (not created), update the fields
                if not created:
                    page.indexing_job_id = job.id
                    page.status = page_status
                    page.document_count = url_result.get('document_count', 0)
                    page.content_size_bytes = url_result.get('content_size_bytes', 0)
                    page.error_message = url_result.get('error_message', '')
                    page.title = url_result.get('title', page.title)
                    page.processed_at = timezone.now()
                    page.save(update_fields=[
                        'indexing_job_id', 'status', 'document_count',
                        'content_size_bytes', 'error_message', 'title', 'processed_at'
                    ])

                stored_count += 1

            except Exception as e:
                self.logger.warning(f"Failed to store indexed page for URL {url_result.get('url', 'unknown')}: {e}")

        self.logger.info(f"Stored {stored_count}/{len(url_results)} indexed pages for job {job.id}")

    def _update_site_stats(self, job, progress_data=None):
        """Update Site statistics when indexing completes"""
        try:
            site = Site.objects.get(id=job.site_id)

            # Count TOTAL indexed pages for this site (not just this job)
            # This gives the overall pages indexed across all jobs
            from .models import IndexedPage
            total_indexed_pages = IndexedPage.objects.filter(
                site_id=job.site_id,
                status='indexed'
            ).count()
            
            # Also count total documents (can be higher due to chunking)
            # For now, use the same value as indexed pages count
            total_documents = total_indexed_pages

            # Update site statistics
            site.indexed_pages_count = total_indexed_pages
            site.total_documents = total_documents
            site.last_indexed_at = timezone.now()
            site.status = 'active'
            
            # Update active namespace if present in job
            update_fields = [
                'indexed_pages_count',
                'total_documents',
                'last_indexed_at',
                'status'
            ]
            
            if job.target_namespace:
                site.active_namespace = job.target_namespace
                update_fields.append('active_namespace')

            site.save(update_fields=update_fields)
            
            self.logger.info(f"Updated Site {site.id} stats: indexed_pages_count={total_indexed_pages}, total_documents={total_documents}, active_namespace={site.active_namespace}")
        except Site.DoesNotExist:
            self.logger.error(f"Site {job.site_id} not found for stats update")
        except Exception as e:
            self.logger.error(f"Failed to update site stats for job {job.id}: {str(e)}")

    def cleanup_excluded_vectors(self, site, pattern):
        """
        Cleanup Pinecone vectors for URLs matching an exclusion pattern.
        
        This is called when a new exclusion pattern is added to remove existing
        indexed content that matches the pattern.
        
        Args:
            site: Site object with the namespace
            pattern: ExcludedURLPattern object to match against
            
        Returns:
            dict: Cleanup results with matched_urls and deleted_count
        """
        from .models import IndexedPage, IndexingJob
        
        self.logger.info(f"Cleaning up vectors for exclusion pattern '{pattern.pattern}'")
        
        # Find all indexed pages that match the pattern
        indexed_pages = IndexedPage.objects.filter(
            site_id=site.id,
            status='indexed'
        )
        
        matching_pages = []
        for page in indexed_pages:
            if pattern.matches_url(page.url):
                matching_pages.append(page)
        
        if not matching_pages:
            self.logger.info(f"No URLs match pattern {pattern.pattern}")
            return {
                'matched_urls': [],
                'deleted_count': 0,
                'affected_pages': 0
            }
            
        # Group by namespace - lookup job for each page to get correct namespace
        pages_by_namespace = {}
        fallback_namespace = site.get_namespace()
        
        # Collect unique job IDs to batch lookup
        job_ids = set(page.indexing_job_id for page in matching_pages if page.indexing_job_id)
        jobs = {job.id: job for job in IndexingJob.objects.filter(id__in=job_ids)}
        
        for page in matching_pages:
            # Determine namespace from job
            ns = fallback_namespace
            if page.indexing_job_id and page.indexing_job_id in jobs:
                job = jobs[page.indexing_job_id]
                if job.target_namespace:
                    ns = job.target_namespace
            
            if ns not in pages_by_namespace:
                pages_by_namespace[ns] = []
            pages_by_namespace[ns].append(page.url)
            
        total_deleted = 0
        
        # Delete vectors for each namespace group
        for ns, urls in pages_by_namespace.items():
            self.logger.info(f"Deleting {len(urls)} vectors from namespace '{ns}'")
            try:
                count = self._delete_vectors_by_urls(ns, urls)
                total_deleted += count
            except Exception as e:
                self.logger.error(f"Failed to delete vectors from {ns}: {e}")

        # Mark pages as skipped
        matching_urls = [p.url for p in matching_pages]
        affected = IndexedPage.objects.filter(
            site_id=site.id,
            url__in=matching_urls
        ).update(
            status='skipped',
            error_message=f'Excluded by pattern: {pattern.pattern}'
        )
        
        # Update pattern stats
        pattern.urls_matched = len(matching_urls)
        pattern.save(update_fields=['urls_matched'])
        
        self.logger.info(f"Cleanup complete: {total_deleted} vectors deleted, {affected} pages marked as skipped")
        
        return {
            'matched_urls': matching_urls,
            'deleted_count': total_deleted,
            'affected_pages': affected
        }

    def delete_namespace(self, namespace):
        """
        Delete an entire namespace from Pinecone.
        Called when a project (Site) is deleted.
        """
        url = f"{self.base_url}/vectors/namespace"
        
        payload = {
            'namespace': namespace
        }
        
        headers = {
            'Content-Type': 'application/json',
        }
        
        # Add auth token if configured
        if self.api_token:
            headers['Authorization'] = f'Bearer {self.api_token}'
        
        try:
            self.logger.info(f"Deleting entire namespace '{namespace}'")
            # Using DELETE method
            response = requests.delete(
                url,
                json=payload,
                headers=headers,
                timeout=60  # Longer timeout for deletion
            )
            
            # Handle 404 gracefully (namespace might not exist)
            if response.status_code == 404:
                self.logger.warning(f"Namespace '{namespace}' not found or endpoint unavailable")
                return False
                
            response.raise_for_status()
            result = response.json()
            self.logger.info(f"Successfully deleted namespace '{namespace}'")
            return True
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Failed to delete namespace '{namespace}': {str(e)}")
            # We don't raise here to ensure site deletion doesn't fail
            return False

    def search_knowledge_base(self, namespace, query, top_k=10):
        """
        Search the knowledge base for relevant content.

        Args:
            namespace: Pinecone namespace to search in
            query: Search query text
            top_k: Number of results to return (1-50)

        Returns:
            dict: Search results with query, namespace, results list, and total_results
        """
        url = f"{self.base_url}/search"

        payload = {
            'query': query,
            'namespace': namespace,
            'top_k': min(max(top_k, 1), 50)  # Clamp to valid range
        }

        headers = {
            'Content-Type': 'application/json',
        }

        # Add auth token if configured
        if self.api_token:
            headers['Authorization'] = f'Bearer {self.api_token}'

        try:
            self.logger.info(f"Searching knowledge base in namespace '{namespace}' with query: '{query[:50]}...'")
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            self.logger.info(f"Search returned {result.get('total_results', 0)} results")
            return result
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Search request failed: {str(e)}")
            raise Exception(f"Failed to search knowledge base: {str(e)}")

    def _enforce_page_limit(self, org_id, requested_max_pages):
        """
        Enforce the max_pages_per_site quota limit.

        Returns the effective max_pages value, clamped to the organization's tier limit.
        This ensures users cannot exceed their tier's page limit even if they request more.

        Args:
            org_id: Organization UUID
            requested_max_pages: The max_pages value requested by the user

        Returns:
            int: The effective max_pages value (clamped if necessary)
        """
        if not org_id:
            # No org context - use a reasonable default cap
            self.logger.warning("No org_id provided for quota enforcement, using default cap of 100")
            return min(requested_max_pages, 100)

        try:
            from apps.usage.services import QuotaService

            # Get the organization's page limit from tier/quota
            page_limit = QuotaService.get_page_limit(org_id)

            # If unlimited (None), just apply a hard cap for safety
            if page_limit is None:
                hard_cap = 10000  # Even enterprise has a hard cap
                effective_limit = min(requested_max_pages, hard_cap)
                self.logger.debug(f"Org {org_id} has unlimited pages, applying hard cap of {hard_cap}")
                return effective_limit

            # Clamp to the organization's tier limit
            effective_limit = min(requested_max_pages, page_limit)

            if effective_limit < requested_max_pages:
                self.logger.info(
                    f"Org {org_id}: Requested {requested_max_pages} pages but tier limit is {page_limit}. "
                    f"Using {effective_limit} pages."
                )

            return effective_limit

        except Exception as e:
            self.logger.error(f"Error enforcing page limit for org {org_id}: {e}")
            # On error, apply a conservative default
            return min(requested_max_pages, 50)

    def _check_quotas(self, org_id, params):
        """
        Check if organization has sufficient quotas for indexing job.
        Raises QuotaExceeded if limits are exceeded.
        """
        if not org_id:
            self.logger.debug("No org_id for quota check - skipping")
            return

        try:
            from apps.usage.services import QuotaService
            from apps.organizations.models import Organization

            # Get organization's plan tier
            try:
                org = Organization.objects.get(id=org_id)
                plan_tier = org.plan_tier or 'basic'
            except Organization.DoesNotExist:
                plan_tier = 'basic'

            # Check concurrent job limit
            allowed, reason = QuotaService.check_indexing_job_quota(org_id, plan_tier)
            if not allowed:
                raise QuotaExceeded(reason, {'limit_type': 'concurrent_jobs'})

            self.logger.debug(f"Quota check passed for org {org_id}")

        except QuotaExceeded:
            raise
        except Exception as e:
            self.logger.error(f"Error checking quotas for org {org_id}: {e}")
            # Don't block on quota check errors - log and continue
            return

    def _estimate_indexing_cost(self, params):
        """Estimate cost for indexing job in cents"""
        max_pages = params.get('max_pages', 100)
        # Rough estimate: $0.01 per page
        return max_pages * 1
