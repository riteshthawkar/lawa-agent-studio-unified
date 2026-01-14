
import pytest
from httpx import AsyncClient
from unittest.mock import MagicMock, patch, ANY

@pytest.mark.asyncio
async def test_exclusion_pattern_remapping(client: AsyncClient, mock_db_manager):
    """Test that pattern_type from DB is remapped to type for CrawlerConfig"""
    
    # Mock DB returning patterns with 'pattern_type'
    # This simulates what DjangoDatabaseManager actually returns
    mock_db_manager.get_excluded_patterns.return_value = [
        {'id': '1', 'pattern': '^/admin/.*', 'pattern_type': 'regex', 'description': 'Admin panel'}
    ]
    
    headers = {"Authorization": "Bearer test-token"}
    payload = {
        "url": "https://example.com",
        "site_id": "site-123", # Trigger DB lookup by providing site_id without patterns in payload
        "max_pages": 10
    }
    
    # We match 'app.CrawlerConfig' because app.py imports it as: from modules.config import CrawlerConfig
    # So inside app.py it is just CrawlerConfig.
    # However, since we import app in conftest (likely), we patch where it is used.
    # 'app.CrawlerConfig' should work if app is the module.
    
    with patch("app.CrawlerConfig") as MockConfig:
        response = await client.post("/index", json=payload, headers=headers)
        
        assert response.status_code == 200, f"Response: {response.text}"
        
        # Verify get_excluded_patterns was called
        mock_db_manager.get_excluded_patterns.assert_called_with("site-123")
        
        # Verify CrawlerConfig received the remapped pattern
        call_args = MockConfig.call_args
        assert call_args is not None, "CrawlerConfig was not instantiated"
        _, kwargs = call_args
        
        excluded_patterns = kwargs.get('excluded_patterns')
        assert excluded_patterns is not None, "excluded_patterns was None"
        assert len(excluded_patterns) == 1
        
        print(f"DEBUG: Actual patterns passed to config: {excluded_patterns}")
        
        # KEY ASSERTION: Ensure 'type' is present and 'pattern_type' is gone
        assert excluded_patterns[0]['pattern'] == '^/admin/.*'
        assert excluded_patterns[0]['type'] == 'regex' 
        assert 'pattern_type' not in excluded_patterns[0]
