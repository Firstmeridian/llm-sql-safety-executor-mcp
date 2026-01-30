"""
Adapter Manager

Manages multiple database adapters (SQL and NoSQL) for the MCP server.
Provides unified access to different datasources based on configuration.

Features:
- Lazy initialization of adapters (only when first accessed)
- Support for multiple concurrent datasources
- Dynamic datasource enablement via environment variables
- Graceful handling of missing adapters

Configuration:
- PRIMARY_DB_TYPE: Main SQL database (mysql, sqlite)
- ENABLED_DATASOURCES: Comma-separated list of enabled datasources
  Example: "mysql,mongodb,redis" or "sqlite,mongodb"

Usage:
    manager = get_adapter_manager()
    
    # Get SQL adapter
    sql_adapter = manager.get_sql_adapter()
    
    # Get NoSQL adapters
    mongo_adapter = manager.get_mongodb_adapter()
    redis_adapter = manager.get_redis_adapter()
    
    # Check what's enabled
    if manager.is_enabled("mongodb"):
        # MongoDB operations
        pass
"""

import logging
import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from db_adapter import DatabaseAdapter
    from mongodb_adapter import MongoDBAdapter
    from redis_adapter import RedisAdapter

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

# Comma-separated list of enabled datasources
# Example: "mysql,mongodb,redis" or "sqlite,mongodb"
ENABLED_DATASOURCES = os.getenv("ENABLED_DATASOURCES", "mysql").lower().split(",")
ENABLED_DATASOURCES = [ds.strip() for ds in ENABLED_DATASOURCES if ds.strip()]

# For backward compatibility, PRIMARY_DB_TYPE is still used for SQL
PRIMARY_DB_TYPE = os.getenv("PRIMARY_DB_TYPE", os.getenv("DB_TYPE", "mysql")).lower()


def get_enabled_datasources() -> list[str]:
    """Get list of enabled datasources."""
    return ENABLED_DATASOURCES.copy()


def is_datasource_enabled(datasource: str) -> bool:
    """Check if a specific datasource is enabled."""
    return datasource.lower() in ENABLED_DATASOURCES


# =============================================================================
# Adapter Manager
# =============================================================================

class AdapterManager:
    """
    Manages database adapters for SQL and NoSQL databases.
    
    Features:
    - Lazy initialization (adapters created on first access)
    - Singleton pattern for adapter instances
    - Dynamic datasource enablement
    - Thread-safe adapter creation with locks
    """
    
    def __init__(self):
        """Initialize adapter manager."""
        self._sql_adapter = None
        self._mongodb_adapter = None
        self._redis_adapter = None
        self._lock = threading.Lock()  # Thread safety for lazy initialization
        
        logger.info(f"AdapterManager initialized with datasources: {ENABLED_DATASOURCES}")
        logger.info(f"Primary SQL type: {PRIMARY_DB_TYPE}")
    
    # =========================================================================
    # SQL Adapter
    # =========================================================================
    
    def get_sql_adapter(self) -> "DatabaseAdapter | None":
        """
        Get the SQL database adapter.
        
        Uses PRIMARY_DB_TYPE to determine which adapter to create.
        
        Returns:
            DatabaseAdapter instance or None if SQL not enabled/available
        """
        # Check if any SQL datasource is enabled
        sql_types = {"mysql", "sqlite"}
        if not any(ds in ENABLED_DATASOURCES for ds in sql_types):
            return None
        
        if self._sql_adapter is None:
            with self._lock:
                if self._sql_adapter is None:  # Double-check locking
                    self._sql_adapter = self._create_sql_adapter()
        
        return self._sql_adapter
    
    def _create_sql_adapter(self) -> "DatabaseAdapter | None":
        """Create the appropriate SQL adapter."""
        try:
            from db_adapter import get_adapter
            return get_adapter()
        except ImportError as e:
            logger.error(f"Failed to import SQL adapter: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to create SQL adapter: {e}")
            return None
    
    # =========================================================================
    # MongoDB Adapter
    # =========================================================================
    
    def get_mongodb_adapter(self) -> "MongoDBAdapter | None":
        """
        Get the MongoDB adapter.
        
        Returns:
            MongoDBAdapter instance or None if MongoDB not enabled/available
        """
        if not is_datasource_enabled("mongodb"):
            return None
        
        if self._mongodb_adapter is None:
            with self._lock:
                if self._mongodb_adapter is None:  # Double-check locking
                    self._mongodb_adapter = self._create_mongodb_adapter()
        
        return self._mongodb_adapter
    
    def _create_mongodb_adapter(self) -> "MongoDBAdapter | None":
        """Create MongoDB adapter."""
        try:
            from mongodb_adapter import get_mongodb_adapter
            adapter = get_mongodb_adapter()
            if adapter.check_connection()[0]:
                return adapter
            else:
                logger.warning("MongoDB adapter created but connection failed")
                return adapter
        except ImportError as e:
            logger.error(f"Failed to import MongoDB adapter: {e}. Install: pip install pymongo")
            return None
        except Exception as e:
            logger.error(f"Failed to create MongoDB adapter: {e}")
            return None
    
    # =========================================================================
    # Redis Adapter
    # =========================================================================
    
    def get_redis_adapter(self) -> "RedisAdapter | None":
        """
        Get the Redis adapter.
        
        Returns:
            RedisAdapter instance or None if Redis not enabled/available
        """
        if not is_datasource_enabled("redis"):
            return None
        
        if self._redis_adapter is None:
            with self._lock:
                if self._redis_adapter is None:  # Double-check locking
                    self._redis_adapter = self._create_redis_adapter()
        
        return self._redis_adapter
    
    def _create_redis_adapter(self) -> "RedisAdapter | None":
        """Create Redis adapter."""
        try:
            from redis_adapter import get_redis_adapter
            adapter = get_redis_adapter()
            if adapter.check_connection()[0]:
                return adapter
            else:
                logger.warning("Redis adapter created but connection failed")
                return adapter
        except ImportError as e:
            logger.error(f"Failed to import Redis adapter: {e}. Install: pip install redis")
            return None
        except Exception as e:
            logger.error(f"Failed to create Redis adapter: {e}")
            return None
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def is_enabled(self, datasource: str) -> bool:
        """Check if a datasource is enabled."""
        return is_datasource_enabled(datasource)
    
    def get_enabled_datasources(self) -> list[str]:
        """Get list of enabled datasources."""
        return get_enabled_datasources()
    
    def check_all_connections(self) -> dict[str, tuple[bool, str]]:
        """
        Check connections for all enabled datasources.
        
        Returns:
            Dictionary of datasource -> (is_connected, message)
        """
        results = {}
        
        # Check SQL
        sql_types = {"mysql", "sqlite"}
        enabled_sql = [ds for ds in ENABLED_DATASOURCES if ds in sql_types]
        if enabled_sql:
            adapter = self.get_sql_adapter()
            if adapter:
                connected, msg = adapter.check_connection()
                results["sql"] = (connected, msg)
            else:
                results["sql"] = (False, "SQL adapter not available")
        
        # Check MongoDB
        if is_datasource_enabled("mongodb"):
            adapter = self.get_mongodb_adapter()
            if adapter:
                connected, msg = adapter.check_connection()
                results["mongodb"] = (connected, msg)
            else:
                results["mongodb"] = (False, "MongoDB adapter not available")
        
        # Check Redis
        if is_datasource_enabled("redis"):
            adapter = self.get_redis_adapter()
            if adapter:
                connected, msg = adapter.check_connection()
                results["redis"] = (connected, msg)
            else:
                results["redis"] = (False, "Redis adapter not available")
        
        return results
    
    def close_all(self) -> None:
        """Close all adapter connections."""
        if self._sql_adapter:
            try:
                self._sql_adapter.close()
            except Exception as e:
                logger.warning(f"Error closing SQL adapter: {e}")
            self._sql_adapter = None
        
        if self._mongodb_adapter:
            try:
                self._mongodb_adapter.close()
            except Exception as e:
                logger.warning(f"Error closing MongoDB adapter: {e}")
            self._mongodb_adapter = None
        
        if self._redis_adapter:
            try:
                self._redis_adapter.close()
            except Exception as e:
                logger.warning(f"Error closing Redis adapter: {e}")
            self._redis_adapter = None
        
        logger.info("All adapters closed")


# =============================================================================
# Global Instance
# =============================================================================

_adapter_manager: AdapterManager | None = None


def get_adapter_manager() -> AdapterManager:
    """
    Get or create the global adapter manager.
    
    Returns:
        The global AdapterManager instance
    """
    global _adapter_manager
    if _adapter_manager is None:
        _adapter_manager = AdapterManager()
    return _adapter_manager


def reset_adapter_manager() -> None:
    """Reset the global adapter manager."""
    global _adapter_manager
    if _adapter_manager is not None:
        _adapter_manager.close_all()
        _adapter_manager = None
