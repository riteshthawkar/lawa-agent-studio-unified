import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
from modules.config import CrawlerConfig, EmbeddingConfig
from app import process_indexing_task

@pytest.mark.asyncio
async def test_background_task_success(mock_db_manager):
    """Test successful background task execution"""
    # Mock mocks
    mock_db_manager.claim_and_start_task.return_value = True
    
    # Mock TwoPhaseProcessor
    with patch("app.TwoPhaseProcessor") as MockProcessor:
        processor_instance = MockProcessor.return_value
        processor_instance.process_website = AsyncMock(return_value={
            "status": "completed",
            "stats": {
                "total_urls_collected": 10,
                "total_urls_processed": 10,
                "total_documents_indexed": 5
            }
        })
        
        crawler_config = CrawlerConfig(start_url="https://example.com")
        embedding_config = EmbeddingConfig()
        
        await process_indexing_task(
            task_id="t1",
            crawler_config=crawler_config,
            embedding_config=embedding_config,
            preloaded_embedder=None,
            start_time=datetime.now(),
            external_job_id="job-1"
        )
        
        # Verify Interactions
        assert mock_db_manager.claim_and_start_task.called
        assert processor_instance.process_website.called
        assert mock_db_manager.update_task_status.call_count >= 2 # collecting_urls, completed
        
        # Verify final status update
        call_args = mock_db_manager.update_task_status.call_args_list[-1]
        assert call_args[0][0] == "t1"
        assert call_args[0][1] == "completed"

@pytest.mark.asyncio
async def test_background_task_failed_processing(mock_db_manager):
    """Test background task handling processor exceptions"""
    mock_db_manager.claim_and_start_task.return_value = True
    
    with patch("app.TwoPhaseProcessor") as MockProcessor:
        processor_instance = MockProcessor.return_value
        processor_instance.process_website.side_effect = Exception("Processing Error")
        
        crawler_config = CrawlerConfig(start_url="https://example.com")
        embedding_config = EmbeddingConfig()
        
        await process_indexing_task(
            task_id="t1",
            crawler_config=crawler_config,
            embedding_config=embedding_config,
            preloaded_embedder=None,
            start_time=datetime.now()
        )
        
        # Verify it handled error
        assert mock_db_manager.update_task_status.call_args[0][1] == "failed"
        assert "Processing Error" in mock_db_manager.update_task_status.call_args[1]["error_message"]

@pytest.mark.asyncio
async def test_background_task_zero_docs_failure(mock_db_manager):
    """Test that 0 indexed docs is treated as failure"""
    mock_db_manager.claim_and_start_task.return_value = True
    
    with patch("app.TwoPhaseProcessor") as MockProcessor:
        processor_instance = MockProcessor.return_value
        processor_instance.process_website = AsyncMock(return_value={
            "status": "completed",
            "stats": {
                "total_urls_processed": 10,
                "total_documents_indexed": 0 # Zero docs
            }
        })
        
        crawler_config = CrawlerConfig(start_url="https://example.com")
        embedding_config = EmbeddingConfig()
        
        await process_indexing_task(
            task_id="t1",
            crawler_config=crawler_config,
            embedding_config=embedding_config,
            preloaded_embedder=None,
            start_time=datetime.now()
        )
        
        # Verify it marked as failed despite processor returning completed
        assert mock_db_manager.update_task_status.call_args[0][1] == "failed"
        assert "No documents were successfully indexed" in mock_db_manager.update_task_status.call_args[1]["error_message"]
