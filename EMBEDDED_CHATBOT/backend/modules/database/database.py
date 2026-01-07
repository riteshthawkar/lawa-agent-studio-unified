"""
Database connection module.
Note: This module is largely deprecated in favor of lawa_integration.py for Django integration.
Only specific utility functions might remain here if needed.
"""
import logging

logger = logging.getLogger(__name__)

# Legacy connection logic has been moved to modules/lawa_integration.py
# The application now uses the Django database schema directly.

async def init_db(pool) -> None:
    """
    Deprecated: Initialization logic moved to Django migrations.
    This function now does nothing to avoid creating conflicting legacy tables.
    """
    if not pool:
        logger.warning("init_db called with no pool")
        return
        
    logger.info("Using Django schema. Skipping legacy table creation.")

async def connect_db():
    """Deprecated: Use lawa_integration.pool instead."""
    logger.warning("connect_db is deprecated. Check app.py for correct pool usage.")
    return None

async def disconnect_db(pool):
    """Deprecated: Use close_lawa_integration instead."""
    pass
