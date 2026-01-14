
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
from modules.config import CrawlerConfig, EmbeddingConfig
from modules.indexing_service import execute_indexing_pipeline

@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    # Mocking async initialize if needed, but processor usually handles it
    return embedder

@pytest.mark.asyncio
async def test_execute_indexing_pipeline_success(mock_db_manager, mock_embedder):
    """Test successful execution of the full pipeline."""
    task_id = "task-123"
    external_job_id = "ext-123"
    start_time = datetime.now()
    
    # Mock DB responses
    mock_db_manager.claim_and_start_task.return_value = True
    
    # Mock TwoPhaseProcessor
    with patch("modules.indexing_service.TwoPhaseProcessor") as MockProcessor:
        processor_instance = MockProcessor.return_value
        processor_instance.process_website = AsyncMock(return_value={
            "status": "completed",
            "stats": {
                "total_urls_collected": 5,
                "total_urls_processed": 5,
                "total_documents_indexed": 5
            },
            "phase1_result": {"some": "data"},
            "phase2_result": {"more": "data"}
        })
        
        crawler_config = CrawlerConfig(start_url="https://example.com")
        embedding_config = EmbeddingConfig()
        
        # Execute Pipeline
        await execute_indexing_pipeline(
            task_id=task_id,
            crawler_config=crawler_config,
            embedding_config=embedding_config,
            preloaded_embedder=mock_embedder,
            start_time=start_time,
            external_job_id=external_job_id
        )
        
        # Verifications
        assert mock_db_manager.claim_and_start_task.called
        assert processor_instance.process_website.called
        
        # Verify status updates using call_args_list to check sequence
        # Should have updated to 'collecting_urls' then 'completed'
        calls = mock_db_manager.update_task_status.call_args_list
        assert len(calls) >= 2
        
        final_call = calls[-1]
        assert final_call[0][0] == task_id
        assert final_call[0][1] == "completed"
        assert final_call[1]["documents_indexed"] == 5

@pytest.mark.asyncio
async def test_execute_indexing_pipeline_claim_fail(mock_db_manager):
    """Test pipeline aborts if task cannot be claimed."""
    mock_db_manager.claim_and_start_task.return_value = False
    
    await execute_indexing_pipeline(
        task_id="task-fail",
        crawler_config=CrawlerConfig(),
        embedding_config=EmbeddingConfig(),
        preloaded_embedder=None,
        start_time=datetime.now()
    )
    
    # Should verify that NO further processing happened
    with patch("modules.indexing_service.TwoPhaseProcessor") as MockProcessor:
        assert not MockProcessor.called
        # Should NOT have updated status beyond claim attempt
        assert not mock_db_manager.update_task_status.called

@pytest.mark.asyncio
async def test_execute_indexing_pipeline_exception_handling(mock_db_manager):
    """Test pipeline handles exceptions gracefully."""
    mock_db_manager.claim_and_start_task.return_value = True
    
    with patch("modules.indexing_service.TwoPhaseProcessor") as MockProcessor:
        processor_instance = MockProcessor.return_value
        processor_instance.process_website.side_effect = Exception("Critical Failure")
        
        await execute_indexing_pipeline(
            task_id="task-error",
            crawler_config=CrawlerConfig(),
            embedding_config=EmbeddingConfig(),
            preloaded_embedder=None,
            start_time=datetime.now()
        )
        
        # Verify it marked as failed
        final_call = mock_db_manager.update_task_status.call_args
        assert final_call[0][1] == "failed"
        assert "Critical Failure" in final_call[1]["error_message"]
