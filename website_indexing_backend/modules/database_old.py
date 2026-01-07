#!/usr/bin/env python3
"""
PostgreSQL Database Module for Task Storage and Management
Provides persistent storage for indexing tasks and results.
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from contextlib import asynccontextmanager
import asyncio
import uuid

import asyncpg
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer, Boolean, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
import json

# Configure logging
logger = logging.getLogger(__name__)

# SQLAlchemy setup
Base = declarative_base()

class IndexingTask(Base):
    """Simplified database model for indexing tasks - MVP version."""
    __tablename__ = "indexing_jobs"
    
    # Primary key and Django compatibility
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)  # Proper UUID type
    task_id = Column(String(36), nullable=True)  # External service task ID
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Core identifiers - simplified for MVP
    site_id = Column(UUID(as_uuid=True), nullable=False)  # Proper UUID type for site_id
    external_job_id = Column(String(128), nullable=True)
    
    # Job configuration - simplified for MVP
    url = Column(Text, nullable=False)
    max_pages = Column(Integer, default=100)
    
    # Task status and progress
    status = Column(String(50), default="queued")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Results and metadata
    error_message = Column(Text, nullable=True)
    
    # Progress tracking
    urls_collected = Column(Integer, default=0)
    urls_processed = Column(Integer, default=0)
    documents_indexed = Column(Integer, default=0)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary for API responses."""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "site_id": self.site_id,
            "external_job_id": self.external_job_id,
            "url": self.url,
            "max_pages": self.max_pages,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
            "urls_collected": self.urls_collected,
            "urls_processed": self.urls_processed,
            "documents_indexed": self.documents_indexed,
        }

class DatabaseManager:
    """Manages PostgreSQL database connections and operations."""
    
    def __init__(self):
        self.engine = None
        self.SessionLocal = None
        self.pool = None
        self._connection_string = None
        
    def _get_connection_string(self) -> str:
        """Get PostgreSQL connection string from environment variables."""
        if self._connection_string:
            return self._connection_string
            
        host = os.getenv("LAWA_DB_PG_HOST")
        port = os.getenv("LAWA_DB_PG_PORT", "5432")
        user = os.getenv("LAWA_DB_PG_USER")
        password = os.getenv("LAWA_DB_PG_PASSWORD")
        database = os.getenv("LAWA_DB_PG_DATABASE")
        
        if not all([host, user, password, database]):
            raise ValueError(
                "Missing required PostgreSQL environment variables: "
                "LAWA_DB_PG_HOST, LAWA_DB_PG_USER, LAWA_DB_PG_PASSWORD, LAWA_DB_PG_DATABASE"
            )
        
        # Use asyncpg connection string for async operations
        self._connection_string = f"postgresql://{user}:{password}@{host}:{port}/{database}"
        
        # SQLAlchemy connection string for sync operations
        self._sqlalchemy_connection_string = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
        
        return self._connection_string
    
    async def _setup_connection(self, conn):
        """Setup connection with proper settings."""
        await conn.execute("SET timezone TO 'UTC'")
        await conn.execute("SET statement_timeout TO '120s'")
        await conn.execute("SET idle_in_transaction_session_timeout TO '60s'")
    
    async def initialize(self):
        """Initialize database connection and create tables."""
        try:
            # Get connection string
            connection_string = self._get_connection_string()
            
            # Create asyncpg connection pool - Production optimized
            self.pool = await asyncpg.create_pool(
                connection_string,
                min_size=10,      # Increased for production
                max_size=50,      # Increased for production
                command_timeout=120,
                server_settings={
                    'application_name': 'lawa_indexing_backend',
                },
                # Additional production settings
                max_queries=50000,
                max_inactive_connection_lifetime=300.0,
                setup=self._setup_connection
            )
            
            # Create SQLAlchemy engine - Production optimized
            self.engine = create_engine(
                self._sqlalchemy_connection_string,
                poolclass=QueuePool,
                pool_size=20,        # Increased for production
                max_overflow=30,     # Increased for production
                pool_pre_ping=True,
                pool_recycle=3600,   # Recycle connections every hour
                echo=False
            )
            
            # Create session factory
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )
            
            # Create tables using SQLAlchemy
            Base.metadata.create_all(bind=self.engine)
            
            logger.info("PostgreSQL database initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL database: {e}")
            raise
    
    async def close(self):
        """Close database connections."""
        if self.pool:
            await self.pool.close()
        if self.engine:
            self.engine.dispose()
        logger.info("PostgreSQL database connections closed")
    
    @asynccontextmanager
    async def get_async_connection(self):
        """Get async database connection from pool."""
        if not self.pool:
            raise RuntimeError("Database not initialized")
        
        async with self.pool.acquire() as connection:
            yield connection
    
    def get_sync_session(self):
        """Get synchronous database session."""
        if not self.SessionLocal:
            raise RuntimeError("Database not initialized")
        return self.SessionLocal()
    
    async def create_task(self, task_data: Dict[str, Any]) -> str:
        """Create a new indexing task in the database."""
        try:
            async with self.get_async_connection() as conn:
                query = """
                    INSERT INTO indexing_jobs (
                        id, task_id, site_id, external_job_id,
                        url, max_pages, status, error_message,
                        urls_collected, urls_processed, documents_indexed,
                        started_at, completed_at, created_at, updated_at
                    ) VALUES (
                        gen_random_uuid(), $1, $2, $3,
                        $4, $5, $6, $7,
                        $8, $9, $10,
                        $11, $12, $13, $14
                    )
                    RETURNING task_id
                """
                
                try:
                    row = await conn.fetchrow(
                        query,
                        task_data["task_id"],                    # $1
                        task_data.get("site_id"),                # $2
                        task_data.get("external_job_id"),        # $3
                        task_data["url"],                        # $4
                        task_data.get("max_pages", 100),         # $5
                        "queued",                                # $6
                        "",                                      # $7 - error_message
                        0,                                       # $8 - urls_collected
                        0,                                       # $9 - urls_processed
                        0,                                       # $10 - documents_indexed
                        None,                                    # $11 - started_at
                        None,                                    # $12 - completed_at
                        datetime.utcnow(),                       # $13 - created_at
                        datetime.utcnow()                        # $14 - updated_at
                    )
                    if row and row.get("task_id"):
                        logger.info(f"Created task {row['task_id']} in database")
                        return row["task_id"]
                except asyncpg.exceptions.PostgresError as e:
                    # Check if it's a unique violation (SQLSTATE 23505)
                    if e.sqlstate == '23505':
                        logger.warning(f"Caught unique constraint violation (SQLSTATE 23505): {e}. Attempting idempotent lookup.")
                        # Idempotent insert: return existing task if conflict
                        existing = None
                        if task_data.get("external_job_id"):
                            existing = await conn.fetchrow(
                                "SELECT task_id FROM indexing_jobs WHERE external_job_id = $1 ORDER BY created_at DESC LIMIT 1",
                                task_data.get("external_job_id")
                            )
                        if existing and existing.get("task_id"):
                            logger.info(
                                f"Duplicate external_job_id detected; returning existing task_id {existing['task_id']}"
                            )
                            return existing["task_id"]
                        else:
                            # If lookup fails, log error but don't raise - this is expected behavior
                            logger.error(f"Could not find existing task for external_job_id: {task_data.get('external_job_id')}")
                            # Return a new task_id to avoid breaking the flow
                            return task_data["task_id"]
                    else:
                        # Not a unique violation, so re-raise
                        raise
        except Exception as e:
            logger.error(f"Error creating task: {e} (type: {type(e)})")
            raise
    
    async def update_task_status(self, task_id: str, status: str, **kwargs) -> bool:
        """Update task status and optional fields."""
        async with self.get_async_connection() as conn:
            # Build dynamic update query
            update_fields = ["status = $2"]
            values = [task_id, status]
            param_count = 2
            
            if "started_at" in kwargs:
                param_count += 1
                update_fields.append(f"started_at = ${param_count}")
                values.append(kwargs["started_at"])
            
            if "completed_at" in kwargs:
                param_count += 1
                update_fields.append(f"completed_at = ${param_count}")
                values.append(kwargs["completed_at"])
            
            if "error_message" in kwargs:
                param_count += 1
                update_fields.append(f"error_message = ${param_count}")
                values.append(kwargs["error_message"])
            
            if "urls_collected" in kwargs:
                param_count += 1
                update_fields.append(f"urls_collected = ${param_count}")
                values.append(kwargs["urls_collected"])
            
            if "urls_processed" in kwargs:
                param_count += 1
                update_fields.append(f"urls_processed = ${param_count}")
                values.append(kwargs["urls_processed"])
            
            if "documents_indexed" in kwargs:
                param_count += 1
                update_fields.append(f"documents_indexed = ${param_count}")
                values.append(kwargs["documents_indexed"])
            
            query = f"UPDATE indexing_jobs SET {', '.join(update_fields)} WHERE task_id = $1"
            
            result = await conn.execute(query, *values)
            return result == "UPDATE 1"
    
    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task by ID."""
        async with self.get_async_connection() as conn:
            query = "SELECT * FROM indexing_jobs WHERE task_id = $1"
            row = await conn.fetchrow(query, task_id)
            
            if not row:
                return None
            
            # Convert row to dictionary
            task_dict = dict(row)
            return task_dict
    
    async def list_tasks(
        self,
        status_filter: Optional[str] = None,
        site_id: Optional[str] = None,
        external_job_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List tasks with optional filters."""
        async with self.get_async_connection() as conn:
            # Build dynamic WHERE clause
            conditions = []
            params = []
            if status_filter:
                conditions.append("status = $%d" % (len(params) + 1))
                params.append(status_filter)
            if site_id:
                conditions.append("site_id = $%d" % (len(params) + 1))
                params.append(site_id)
            if external_job_id:
                conditions.append("external_job_id = $%d" % (len(params) + 1))
                params.append(external_job_id)
            
            where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            query = f"SELECT * FROM indexing_jobs{where_clause} ORDER BY created_at DESC LIMIT $%d" % (len(params) + 1)
            params.append(limit)
            rows = await conn.fetch(query, *params)
            
            tasks = []
            for row in rows:
                task_dict = dict(row)
                tasks.append(task_dict)
            
            return tasks

    async def get_task_by_external_job(self, external_job_id: str) -> Optional[Dict[str, Any]]:
        """Get most recent task by external_job_id for idempotency."""
        try:
            async with self.get_async_connection() as conn:
                query = """
                    SELECT * FROM indexing_jobs 
                    WHERE external_job_id = $1 
                    ORDER BY created_at DESC LIMIT 1
                """
                row = await conn.fetchrow(query, external_job_id)
                if not row:
                    return None
                task_dict = dict(row)
                return task_dict
        except Exception as e:
            logger.error(f"Error getting task by external job: {e}")
            return None

    
    async def get_task_stats(self) -> Dict[str, Any]:
        """Get task statistics."""
        async with self.get_async_connection() as conn:
            # Get counts by status
            query = """
                SELECT status, COUNT(*) as count 
                FROM indexing_jobs 
                GROUP BY status
            """
            rows = await conn.fetch(query)
            
            stats = {}
            total_tasks = 0
            
            for row in rows:
                stats[row["status"]] = row["count"]
                total_tasks += row["count"]
            
            # Calculate success rate
            completed = stats.get("completed", 0)
            failed = stats.get("failed", 0)
            success_rate = (completed / (completed + failed) * 100) if (completed + failed) > 0 else 0
            
            return {
                "total_tasks": total_tasks,
                "by_status": stats,
                "success_rate": round(success_rate, 2),
                "active_tasks": stats.get("collecting_urls", 0) + stats.get("processing_urls", 0),
                "completed_tasks": completed
            }
    
    async def cleanup_old_tasks(self, days_old: int = 30) -> int:
        """Clean up old completed tasks."""
        async with self.get_async_connection() as conn:
            query = """
                DELETE FROM indexing_jobs 
                WHERE status IN ('completed', 'failed') 
                AND completed_at < NOW() - INTERVAL '%s days'
            """ % days_old
            
            result = await conn.execute(query)
            deleted_count = int(result.split()[-1])
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old tasks")
            
            return deleted_count

# Global database manager instance
db_manager = DatabaseManager()
