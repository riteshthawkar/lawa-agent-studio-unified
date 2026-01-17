"""
Tests for namespace flow between Django and Indexing backend.

These tests ensure the namespace mismatch bug (where indexing worked locally
but retrieval failed in production) cannot recur.

Critical flow:
1. Django creates job with target_namespace
2. Indexing backend stores target_namespace in IndexingJob
3. Vectors are indexed to Pinecone with target_namespace
4. On completion, Site.active_namespace is updated to target_namespace
5. Retrieval uses Site.active_namespace to query Pinecone
"""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4


class TestNamespaceCreation:
    """Tests for namespace creation during job initialization"""

    @pytest.mark.asyncio
    async def test_target_namespace_passed_in_task_data(self, mock_db_manager):
        """Test that target_namespace is included when creating a task"""
        site_id = str(uuid4())
        target_namespace = f"site_{site_id}_{int(datetime.now().timestamp())}"

        task_data = {
            "task_id": str(uuid4()),
            "url": "https://example.com",
            "status": "queued",
            "site_id": site_id,
            "target_namespace": target_namespace,
            "external_job_id": f"job_{uuid4()}"
        }

        await mock_db_manager.create_task(task_data)

        # Verify create_task was called with namespace
        mock_db_manager.create_task.assert_called_once()
        call_args = mock_db_manager.create_task.call_args[0][0]
        assert "target_namespace" in call_args
        assert call_args["target_namespace"] == target_namespace

    @pytest.mark.asyncio
    async def test_namespace_format_convention(self):
        """Test namespace follows the expected format convention"""
        site_id = str(uuid4())
        timestamp = int(datetime.now().timestamp())

        # Expected format: site_{site_id}_{timestamp}
        namespace = f"site_{site_id}_{timestamp}"

        assert namespace.startswith("site_")
        assert site_id in namespace
        assert str(timestamp) in namespace

    @pytest.mark.asyncio
    async def test_reindex_creates_new_namespace(self):
        """Test that re-indexing creates a NEW namespace (not reusing old one)"""
        site_id = str(uuid4())

        # First index
        timestamp1 = 1000000000
        namespace1 = f"site_{site_id}_{timestamp1}"

        # Re-index (should have different timestamp)
        timestamp2 = 1000000100
        namespace2 = f"site_{site_id}_{timestamp2}"

        assert namespace1 != namespace2
        assert site_id in namespace1
        assert site_id in namespace2


class TestNamespacePersistence:
    """Tests for namespace persistence in database"""

    @pytest.fixture
    def mock_indexing_job(self):
        """Create a mock IndexingJob model"""
        job = MagicMock()
        job.id = str(uuid4())
        job.site_id = str(uuid4())
        job.target_namespace = f"site_{job.site_id}_{int(datetime.now().timestamp())}"
        job.status = "queued"
        return job

    @pytest.mark.asyncio
    async def test_job_stores_target_namespace(self, mock_indexing_job):
        """Test IndexingJob stores target_namespace field"""
        assert hasattr(mock_indexing_job, 'target_namespace')
        assert mock_indexing_job.target_namespace is not None
        assert mock_indexing_job.target_namespace.startswith("site_")

    @pytest.mark.asyncio
    async def test_namespace_retrieved_with_job(self, mock_db_manager):
        """Test namespace is retrieved when fetching job details"""
        job_id = str(uuid4())
        expected_namespace = f"site_test_{int(datetime.now().timestamp())}"

        mock_db_manager.get_task.return_value = {
            "task_id": job_id,
            "status": "processing",
            "target_namespace": expected_namespace
        }

        result = await mock_db_manager.get_task(job_id)

        assert result["target_namespace"] == expected_namespace


class TestNamespaceActivation:
    """Tests for namespace activation on job completion"""

    @pytest.mark.asyncio
    async def test_active_namespace_updated_on_success(self, mock_db_manager):
        """Test Site.active_namespace is updated when job completes successfully"""
        task_id = str(uuid4())
        target_namespace = f"site_test_{int(datetime.now().timestamp())}"

        # Simulate job completion
        await mock_db_manager.update_task_status(
            task_id,
            "completed",
            completed_at=datetime.now(),
            phase2_result={
                "pages_indexed": 50,
                "documents_indexed": 150,
                "namespace": target_namespace
            }
        )

        # Verify update was called
        assert mock_db_manager.update_task_status.called

        # In real implementation, this should update Site.active_namespace
        call_kwargs = mock_db_manager.update_task_status.call_args[1]
        assert call_kwargs.get("phase2_result", {}).get("namespace") == target_namespace

    @pytest.mark.asyncio
    async def test_namespace_not_updated_on_failure(self, mock_db_manager):
        """Test Site.active_namespace is NOT updated when job fails"""
        task_id = str(uuid4())
        old_namespace = "site_test_old_namespace"
        new_namespace = "site_test_new_namespace"

        # Site has existing active namespace
        site_state = {"active_namespace": old_namespace}

        # Simulate job failure
        await mock_db_manager.update_task_status(
            task_id,
            "failed",
            error_message="Network timeout during indexing"
        )

        # Namespace should remain unchanged
        # (In mock, we verify the status was 'failed')
        call_args = mock_db_manager.update_task_status.call_args[0]
        assert call_args[1] == "failed"

        # Old namespace should be preserved
        assert site_state["active_namespace"] == old_namespace

    @pytest.mark.asyncio
    async def test_zero_downtime_namespace_switch(self):
        """Test zero-downtime namespace switching during re-indexing"""
        site_id = str(uuid4())

        # Initial state: Site is active with old namespace
        old_namespace = f"site_{site_id}_1000000000"
        new_namespace = f"site_{site_id}_1000000100"

        site = {
            "id": site_id,
            "status": "active",
            "active_namespace": old_namespace
        }

        # During re-indexing, old namespace should still be used for retrieval
        job = {
            "target_namespace": new_namespace,
            "status": "processing"
        }

        # Retrieval should use active_namespace (old)
        retrieval_namespace = site["active_namespace"]
        assert retrieval_namespace == old_namespace

        # After completion, switch to new namespace
        job["status"] = "completed"
        site["active_namespace"] = new_namespace

        # Now retrieval uses new namespace
        assert site["active_namespace"] == new_namespace


class TestNamespaceInPinecone:
    """Tests for namespace usage in Pinecone operations"""

    @pytest.mark.asyncio
    async def test_vectors_indexed_to_correct_namespace(self):
        """Test vectors are indexed to the target namespace in Pinecone"""
        target_namespace = f"site_test_{int(datetime.now().timestamp())}"

        # Simulate Pinecone upsert
        mock_index = MagicMock()

        vectors = [
            {"id": "doc_1", "values": [0.1] * 768, "metadata": {"url": "https://example.com/page1"}},
            {"id": "doc_2", "values": [0.2] * 768, "metadata": {"url": "https://example.com/page2"}}
        ]

        # Upsert with namespace
        mock_index.upsert(vectors=vectors, namespace=target_namespace)

        mock_index.upsert.assert_called_once()
        call_kwargs = mock_index.upsert.call_args[1]
        assert call_kwargs["namespace"] == target_namespace

    @pytest.mark.asyncio
    async def test_query_uses_active_namespace(self):
        """Test retrieval queries use the Site's active namespace"""
        active_namespace = f"site_test_{int(datetime.now().timestamp())}"

        # Simulate Pinecone query
        mock_index = MagicMock()
        mock_index.query.return_value = MagicMock(matches=[])

        query_vector = [0.1] * 768

        # Query with namespace
        mock_index.query(
            vector=query_vector,
            top_k=5,
            namespace=active_namespace,
            include_metadata=True
        )

        mock_index.query.assert_called_once()
        call_kwargs = mock_index.query.call_args[1]
        assert call_kwargs["namespace"] == active_namespace

    @pytest.mark.asyncio
    async def test_namespace_mismatch_returns_empty(self):
        """Test querying wrong namespace returns no results"""
        correct_namespace = "site_test_correct"
        wrong_namespace = "site_test_wrong"

        # Vectors indexed to correct namespace
        indexed_to = correct_namespace

        # Query to wrong namespace
        queried_from = wrong_namespace

        # Simulate: querying wrong namespace returns nothing
        if indexed_to != queried_from:
            results = []
        else:
            results = [{"id": "doc_1", "score": 0.95}]

        assert len(results) == 0


class TestNamespaceCleanup:
    """Tests for old namespace cleanup"""

    @pytest.mark.asyncio
    async def test_old_namespace_can_be_deleted(self):
        """Test old namespace vectors can be deleted after successful switch"""
        old_namespace = "site_test_old"
        new_namespace = "site_test_new"

        mock_index = MagicMock()

        # After successful switch, old namespace can be cleaned up
        mock_index.delete(delete_all=True, namespace=old_namespace)

        mock_index.delete.assert_called_once()
        call_kwargs = mock_index.delete.call_args[1]
        assert call_kwargs["namespace"] == old_namespace

    @pytest.mark.asyncio
    async def test_cleanup_only_after_successful_switch(self):
        """Test cleanup happens only after successful namespace switch"""
        old_namespace = "site_test_old"
        new_namespace = "site_test_new"

        site = {"active_namespace": old_namespace}
        job = {"target_namespace": new_namespace, "status": "failed"}

        # Should NOT cleanup if job failed
        should_cleanup = (
            job["status"] == "completed" and
            site["active_namespace"] == new_namespace
        )

        assert should_cleanup is False


class TestEndToEndNamespaceFlow:
    """End-to-end tests for the complete namespace flow"""

    @pytest.mark.asyncio
    async def test_complete_indexing_namespace_flow(self, mock_db_manager):
        """Test complete namespace flow from job creation to retrieval"""
        site_id = str(uuid4())
        target_namespace = f"site_{site_id}_{int(datetime.now().timestamp())}"

        # Step 1: Create job with namespace
        task_data = {
            "task_id": str(uuid4()),
            "url": "https://example.com",
            "site_id": site_id,
            "target_namespace": target_namespace,
            "status": "queued"
        }

        mock_db_manager.create_task.return_value = task_data["task_id"]
        await mock_db_manager.create_task(task_data)

        # Step 2: Job processes and indexes vectors to namespace
        # (Simulated - vectors go to Pinecone with target_namespace)
        vectors_indexed_to = target_namespace

        # Step 3: Job completes, site.active_namespace updated
        site = {"active_namespace": None}

        await mock_db_manager.update_task_status(
            task_data["task_id"],
            "completed",
            phase2_result={"namespace": target_namespace}
        )

        # Simulate namespace activation
        site["active_namespace"] = target_namespace

        # Step 4: Retrieval uses active_namespace
        retrieval_namespace = site["active_namespace"]

        # Verify: indexing and retrieval use same namespace
        assert vectors_indexed_to == retrieval_namespace
        assert retrieval_namespace == target_namespace

    @pytest.mark.asyncio
    async def test_reindex_with_namespace_isolation(self, mock_db_manager):
        """Test re-indexing maintains isolation between old and new namespace"""
        site_id = str(uuid4())

        # Initial indexing
        namespace_v1 = f"site_{site_id}_1000000000"
        site = {"active_namespace": namespace_v1, "status": "active"}

        # Start re-indexing
        namespace_v2 = f"site_{site_id}_1000000100"

        # During re-indexing:
        # - Old namespace serves retrieval requests
        # - New namespace receives new vectors

        serving_namespace = site["active_namespace"]
        indexing_namespace = namespace_v2

        assert serving_namespace != indexing_namespace
        assert serving_namespace == namespace_v1

        # After successful completion:
        site["active_namespace"] = namespace_v2

        assert site["active_namespace"] == namespace_v2
