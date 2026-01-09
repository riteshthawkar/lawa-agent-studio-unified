"""
Two-phase processor module for website indexing.
Phase 1: Collect all URLs from website (with page limit check)
Phase 2: Process each URL iteratively (cleaning → embedding → indexing)
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional, Callable, Awaitable
from urllib.parse import urlparse

from .url_collector import URLCollector
from .iterative_processor import IterativeProcessor
from .config import CrawlerConfig, EmbeddingConfig

logger = logging.getLogger(__name__)


class TwoPhaseProcessor:
    """
    Two-phase website processor:
    1. Collect all URLs from website (with page limit validation)
    2. Process each URL iteratively (cleaning → embedding → indexing)
    """
    
    def __init__(
        self,
        crawler_config: CrawlerConfig,
        embedding_config: EmbeddingConfig,
        preloaded_embedder=None,
        db_manager=None,
        task_id=None,
        progress_callback: Optional[Callable[[str, int, int, int], Awaitable[None]]] = None
    ):
        self.crawler_config = crawler_config
        self.embedding_config = embedding_config
        self.db_manager = db_manager
        self.task_id = task_id
        self.progress_callback = progress_callback

        # Initialize components
        self.url_collector = URLCollector(crawler_config)
        self.iterative_processor = IterativeProcessor(
            embedding_config,
            preloaded_embedder,
            db_manager=db_manager,
            task_id=task_id,
            progress_callback=progress_callback
        )

        # Overall stats
        self.overall_stats = {
            "phase1_status": None,
            "phase2_status": None,
            "total_urls_collected": 0,
            "total_urls_processed": 0,
            "total_documents_indexed": 0,
            "total_duration": None,
            "start_time": None
        }

        logger.info("TwoPhaseProcessor initialized with Crawl4AI")

    def _generate_namespace(self, url: str) -> str:
        """Generate a namespace based on the website domain."""
        try:
            parsed_url = urlparse(url)
            domain = parsed_url.netloc.lower()
            
            # Remove www. prefix if present
            if domain.startswith('www.'):
                domain = domain[4:]
            
            # Replace dots and special characters with underscores
            namespace = domain.replace('.', '_').replace('-', '_')
            
            # Add prefix if configured
            if self.embedding_config.namespace_prefix:
                namespace = f"{self.embedding_config.namespace_prefix}_{namespace}"
            
            logger.debug(f"Generated namespace '{namespace}' for URL: {url}")
            return namespace
            
        except Exception as e:
            logger.error(f"Error generating namespace for URL {url}: {e}")
            # Fallback to a default namespace
            return f"{self.embedding_config.namespace_prefix}_default" if self.embedding_config.namespace_prefix else "default"

    async def process_website(self) -> Dict[str, Any]:
        """
        Process a website in two phases:
        1. Collect all URLs (with page limit check)
        2. Process each URL iteratively
        """
        try:
            import time
            self.overall_stats["start_time"] = time.time()
            
            logger.info("🚀 Starting two-phase website processing with Crawl4AI")
            logger.info("=" * 60)
            
            # Phase 1: URL Collection (using Crawl4AI)
            logger.info("📋 Phase 1: Collecting URLs from website using Crawl4AI Deep Crawl")
            logger.info(f"   Target URL: {self.crawler_config.start_url}")
            logger.info(f"   Max pages: {self.crawler_config.max_pages}")
            
            phase1_result = await self.url_collector.collect_all_urls()
            self.overall_stats["phase1_status"] = phase1_result["status"]
            
            if phase1_result["status"] != "completed":
                logger.error(f"Phase 1 failed: {phase1_result.get('error', 'Unknown error')}")
                return {
                    "status": "failed",
                    "phase": "url_collection",
                    "error": phase1_result.get("error", "URL collection failed"),
                    "stats": self.overall_stats
                }
            
            # Check if we have URLs to process
            collected_urls = phase1_result["urls"]
            crawl_results = phase1_result.get("results", [])
            self.overall_stats["total_urls_collected"] = len(collected_urls)
            
            if not collected_urls:
                logger.warning("No URLs collected from website")
                return {
                    "status": "completed",
                    "message": "No URLs found to process",
                    "stats": self.overall_stats
                }
            
            # P2.1/P2.2: Apply exclusion patterns and merge user-added URLs
            site_id = getattr(self.crawler_config, 'site_id', None)
            if site_id and self.db_manager:
                try:
                    # P2.1: Filter out URLs matching exclusion patterns
                    excluded_patterns = await self.db_manager.get_excluded_patterns(site_id)
                    if excluded_patterns:
                        original_count = len(collected_urls)
                        filtered_urls = [
                            url for url in collected_urls 
                            if not self.db_manager.url_matches_exclusion(url, excluded_patterns)
                        ]
                        excluded_count = original_count - len(filtered_urls)
                        collected_urls = filtered_urls
                        
                        # Also filter crawl_results to match
                        if crawl_results:
                            url_set = set(collected_urls)
                            crawl_results = [r for r in crawl_results if r.url in url_set]
                        
                        if excluded_count > 0:
                            logger.info(f"   P2.1: Excluded {excluded_count} URLs matching exclusion patterns")
                    
                    # P2.2: Merge in user-added URLs
                    user_added_urls = await self.db_manager.get_user_added_urls(site_id)
                    if user_added_urls:
                        url_set = set(collected_urls)
                        new_user_urls = [url for url in user_added_urls if url not in url_set]
                        if new_user_urls:
                            collected_urls.extend(new_user_urls)
                            logger.info(f"   P2.2: Added {len(new_user_urls)} user-added URLs to processing queue")
                
                except Exception as e:
                    logger.warning(f"Could not apply exclusions/user URLs (continuing): {e}")
            
            # STRICT LIMIT ENFORCEMENT: Cap URLs to max_pages
            # This ensures tier limits are respected even if crawling overshoots
            max_allowed = self.crawler_config.max_pages
            if len(collected_urls) > max_allowed:
                logger.warning(f"   ⚠️ Collected {len(collected_urls)} URLs, capping to tier limit of {max_allowed}")
                # Keep first N URLs (BFS order = most important pages first)
                collected_urls = collected_urls[:max_allowed]
                # Also cap crawl_results to match
                if crawl_results:
                    url_set = set(collected_urls)
                    crawl_results = [r for r in crawl_results if r.url in url_set]
            
            # Update the count after filtering
            self.overall_stats["total_urls_collected"] = len(collected_urls)
            
            logger.info(f"✅ Phase 1 completed: Collected {len(collected_urls)} URLs (after filtering)")
            logger.info(f"   Collection stats: {phase1_result['stats']}")

            # Update database with collected URLs count
            if self.db_manager and self.task_id:
                await self.db_manager.update_task_status(
                    self.task_id,
                    "processing_urls",
                    urls_collected=len(collected_urls)
                )

            # Send progress webhook after Phase 1 completion
            if self.progress_callback:
                try:
                    await self.progress_callback(
                        "processing_urls",
                        len(collected_urls),
                        0,
                        0
                    )
                except Exception as e:
                    logger.debug(f"Progress callback failed (non-critical): {e}")
            
            # Phase 2: Iterative Processing (using Crawl4AI)
            logger.info("🔄 Phase 2: Processing URLs iteratively with Crawl4AI")
            logger.info(f"   Processing {len(collected_urls)} URLs (using pre-fetched content where available)")
            
            # Generate namespace for this website
            namespace = None
            if self.embedding_config.use_namespaces:
                if getattr(self.embedding_config, "namespace_override", None):
                    namespace = self.embedding_config.namespace_override
                    logger.info(f"   Using namespace override: {namespace}")
                else:
                    namespace = self._generate_namespace(self.crawler_config.start_url)
                    logger.info(f"   Using namespace: {namespace}")
            
            # Use the new process_crawl_results method if results are available
            if crawl_results:
                phase2_result = await self.iterative_processor.process_crawl_results(crawl_results, namespace)
            else:
                # Fallback to legacy URL processing (re-fetching)
                phase2_result = await self.iterative_processor.process_urls_iteratively(collected_urls, namespace)
                
            self.overall_stats["phase2_status"] = phase2_result["status"]
            
            if phase2_result["status"] != "completed":
                logger.error(f"Phase 2 failed: {phase2_result.get('error', 'Unknown error')}")
                return {
                    "status": "failed",
                    "phase": "iterative_processing",
                    "error": phase2_result.get("error", "Iterative processing failed"),
                    "stats": self.overall_stats
                }
            
            # Update overall stats
            self.overall_stats["total_urls_processed"] = phase2_result["stats"]["urls_processed"]
            self.overall_stats["total_documents_indexed"] = phase2_result["stats"]["documents_indexed"]
            
            # Final database update with all stats
            if self.db_manager and self.task_id:
                await self.db_manager.update_task_status(
                    self.task_id,
                    "processing_urls",
                    urls_processed=phase2_result["stats"]["urls_processed"],
                    documents_indexed=phase2_result["stats"]["documents_indexed"]
                )
            self.overall_stats["total_duration"] = time.time() - self.overall_stats["start_time"]
            
            logger.info(f"✅ Phase 2 completed: Processed {phase2_result['stats']['urls_processed']} URLs")
            logger.info(f"   Processing stats: {phase2_result['stats']}")
            
            # Final summary
            logger.info("🎉 Two-phase processing completed successfully with Crawl4AI!")
            logger.info("=" * 60)
            logger.info(f"📊 Final Summary:")
            logger.info(f"   - URLs collected: {self.overall_stats['total_urls_collected']}")
            logger.info(f"   - URLs processed: {self.overall_stats['total_urls_processed']}")
            logger.info(f"   - Documents indexed: {self.overall_stats['total_documents_indexed']}")
            logger.info(f"   - Total duration: {self.overall_stats['total_duration']:.2f} seconds")
            
            return {
                "status": "completed",
                "message": f"Successfully processed {self.overall_stats['total_urls_processed']} URLs and indexed {self.overall_stats['total_documents_indexed']} documents",
                "phase1_result": phase1_result,
                "phase2_result": phase2_result,
                "stats": self.overall_stats
            }
            
        except Exception as e:
            logger.error(f"Error in two-phase processing: {e}")
            self.overall_stats["total_duration"] = time.time() - self.overall_stats["start_time"] if self.overall_stats["start_time"] else None
            
            return {
                "status": "failed",
                "error": str(e),
                "stats": self.overall_stats
            }
        
        finally:
            # Production Fix #2: Memory cleanup after processing
            # Clear large crawl results to free memory for large sites
            try:
                if 'crawl_results' in locals() and crawl_results:
                    crawl_results.clear()
                if 'collected_urls' in locals() and collected_urls:
                    collected_urls.clear() if hasattr(collected_urls, 'clear') else None
                import gc
                gc.collect()
                logger.debug("Memory cleanup completed after two-phase processing")
            except Exception as cleanup_err:
                logger.debug(f"Memory cleanup warning (non-critical): {cleanup_err}")
            
            # Cleanup executor pools in iterative processor
            try:
                await self.iterative_processor.close()
            except Exception as pool_err:
                logger.debug(f"Executor cleanup warning (non-critical): {pool_err}")

    def get_overall_stats(self) -> Dict[str, Any]:
        """Get overall processing statistics."""
        return self.overall_stats.copy()

    def get_phase1_stats(self) -> Dict[str, Any]:
        """Get Phase 1 (URL collection) statistics."""
        return self.url_collector.get_stats()

    def get_phase2_stats(self) -> Dict[str, Any]:
        """Get Phase 2 (iterative processing) statistics."""
        return self.iterative_processor.get_stats()
