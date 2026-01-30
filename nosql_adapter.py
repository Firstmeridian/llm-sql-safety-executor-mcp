"""
NoSQL Database Adapter Module

Provides abstract base classes for NoSQL database backends (MongoDB, Redis).
Uses separate inheritance hierarchy from SQL adapters to avoid leaky abstractions.

Architecture Decision:
- NoSQL adapters are COMPLETELY SEPARATE from DatabaseAdapter (SQL)
- Each NoSQL type has its own ABC: DocumentStoreAdapter, KeyValueStoreAdapter
- This avoids forcing SQL concepts (tables, columns, rows) onto NoSQL
- Reference: "Rule of Three" - avoid premature abstraction

Design Decisions:
- DocumentStoreAdapter for MongoDB (document databases)
- KeyValueStoreAdapter for Redis (key-value stores)
- SearchEngineAdapter reserved for future Elasticsearch support
- Each adapter type has methods matching its natural query patterns

Security:
- All adapters are READ-ONLY by design
- Dangerous operations are blocked at adapter level
- Additional safety checks in nosql_safety_checker.py

References:
- MongoDB MCP Server: https://github.com/mongodb-js/mongodb-mcp-server
- PyMongo Best Practices: https://pymongo.readthedocs.io/en/stable/
- redis-py Documentation: https://redis-py.readthedocs.io/en/stable/
"""

import os
import logging
from abc import ABC, abstractmethod
from typing import Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# MongoDB Configuration
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "test")
MONGODB_TIMEOUT_MS = int(os.getenv("MONGODB_TIMEOUT_MS", "30000"))  # 30s default
MONGODB_MAX_POOL_SIZE = int(os.getenv("MONGODB_MAX_POOL_SIZE", "100"))

# Redis Configuration
REDIS_URI = os.getenv("REDIS_URI", "redis://localhost:6379/0")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_SOCKET_TIMEOUT = int(os.getenv("REDIS_SOCKET_TIMEOUT", "5"))  # 5s command timeout
REDIS_CONNECT_TIMEOUT = int(os.getenv("REDIS_CONNECT_TIMEOUT", "10"))  # 10s connect timeout
REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))

# Result limits (consistent with SQL adapter)
MAX_RESULT_DOCS = int(os.getenv("MAX_RESULT_DOCS", "100"))  # Max documents to return
MAX_RESULT_KEYS = int(os.getenv("MAX_RESULT_KEYS", "1000"))  # Max keys in scan


# =============================================================================
# Document Store Adapter (MongoDB)
# =============================================================================

class DocumentStoreAdapter(ABC):
    """
    Abstract base class for document database adapters (MongoDB, etc.).
    
    Provides interface for document-oriented operations:
    - find: Query documents with filters
    - aggregate: Run aggregation pipelines
    - list_collections: Get collection names
    - get_collection_schema: Sample-based schema inference
    
    Design Note:
    - Separate from SQL DatabaseAdapter to avoid leaky abstractions
    - Methods match natural document database operations
    - Schema is inferred from sampling (NoSQL is schema-less)
    """
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Establish database connection.
        
        Returns:
            True if connection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def find(
        self,
        collection: str,
        filter: dict | None = None,
        projection: dict | None = None,
        limit: int = 100,
        skip: int = 0,
        sort: list[tuple[str, int]] | None = None,
        database: str | None = None
    ) -> list[dict] | str:
        """
        Find documents matching filter criteria.
        
        Args:
            collection: Collection name to query
            filter: Query filter (MongoDB query document)
            projection: Fields to include/exclude
            limit: Maximum documents to return (default 100)
            skip: Number of documents to skip
            sort: Sort specification [(field, direction), ...]
            database: Database name (uses default if not specified)
            
        Returns:
            List of documents on success, error string on failure
        """
        pass
    
    @abstractmethod
    def aggregate(
        self,
        collection: str,
        pipeline: list[dict],
        database: str | None = None
    ) -> list[dict] | str:
        """
        Execute an aggregation pipeline.
        
        Note: Pipeline is validated by safety checker before execution.
        Dangerous stages ($out, $merge) are blocked.
        
        Args:
            collection: Collection name
            pipeline: Aggregation pipeline stages
            database: Database name (uses default if not specified)
            
        Returns:
            Aggregation results on success, error string on failure
        """
        pass
    
    @abstractmethod
    def count_documents(
        self,
        collection: str,
        filter: dict | None = None,
        database: str | None = None
    ) -> int | str:
        """
        Count documents matching filter.
        
        Args:
            collection: Collection name
            filter: Query filter (optional)
            database: Database name (uses default if not specified)
            
        Returns:
            Document count on success, error string on failure
        """
        pass
    
    @abstractmethod
    def list_databases(self) -> list[str] | str:
        """
        List all accessible databases.
        
        Returns:
            List of database names on success, error string on failure
        """
        pass
    
    @abstractmethod
    def list_collections(self, database: str | None = None) -> list[dict] | str:
        """
        List collections in a database with metadata.
        
        Args:
            database: Database name (uses default if not specified)
            
        Returns:
            List of dicts with 'name' and 'document_count' keys,
            or error string on failure
        """
        pass
    
    @abstractmethod
    def get_collection_schema(
        self,
        collection: str,
        sample_size: int = 100,
        database: str | None = None
    ) -> dict | str:
        """
        Infer collection schema by sampling documents.
        
        Args:
            collection: Collection name
            sample_size: Number of documents to sample
            database: Database name (uses default if not specified)
            
        Returns:
            Schema dict with field names and types, or error string
        """
        pass
    
    @abstractmethod
    def check_connection(self) -> tuple[bool, str]:
        """
        Check if database connection is working.
        
        Returns:
            (success, message) tuple
        """
        pass
    
    @abstractmethod
    def get_server_info(self) -> dict | str:
        """
        Get server information and version.
        
        Returns:
            Server info dict or error string
        """
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close database connection and cleanup resources."""
        pass
    
    @property
    @abstractmethod
    def db_type(self) -> str:
        """Return database type identifier ('mongodb', etc.)."""
        pass
    
    @property
    @abstractmethod
    def default_database(self) -> str:
        """Return default database name."""
        pass


# =============================================================================
# Key-Value Store Adapter (Redis)
# =============================================================================

class KeyValueStoreAdapter(ABC):
    """
    Abstract base class for key-value store adapters (Redis, etc.).
    
    Provides interface for key-value operations:
    - get/mget: Retrieve values by key
    - scan: Iterate keys matching pattern
    - type: Get value type
    - Data type specific methods: hgetall, lrange, smembers, zrange
    
    Design Note:
    - Redis has multiple data types (string, hash, list, set, sorted set)
    - Each type has different retrieval methods
    - All methods are READ-ONLY
    """
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection to key-value store.
        
        Returns:
            True if connection successful, False otherwise
        """
        pass
    
    @abstractmethod
    def get(self, key: str) -> Any | str:
        """
        Get value for a string key.
        
        Args:
            key: The key to retrieve
            
        Returns:
            Value on success, error string on failure
        """
        pass
    
    @abstractmethod
    def mget(self, keys: list[str]) -> list[Any] | str:
        """
        Get values for multiple keys.
        
        Args:
            keys: List of keys to retrieve
            
        Returns:
            List of values on success, error string on failure
        """
        pass
    
    @abstractmethod
    def hgetall(self, key: str) -> dict | str:
        """
        Get all fields and values of a hash.
        
        Args:
            key: Hash key
            
        Returns:
            Dict of field-value pairs, or error string
        """
        pass
    
    @abstractmethod
    def lrange(self, key: str, start: int = 0, stop: int = -1) -> list | str:
        """
        Get elements from a list.
        
        Args:
            key: List key
            start: Start index (default 0)
            stop: Stop index (default -1 for all)
            
        Returns:
            List of elements, or error string
        """
        pass
    
    @abstractmethod
    def smembers(self, key: str) -> set | str:
        """
        Get all members of a set.
        
        Args:
            key: Set key
            
        Returns:
            Set of members, or error string
        """
        pass
    
    @abstractmethod
    def zrange(
        self,
        key: str,
        start: int = 0,
        stop: int = -1,
        withscores: bool = False
    ) -> list | str:
        """
        Get elements from a sorted set by index.
        
        Args:
            key: Sorted set key
            start: Start index
            stop: Stop index
            withscores: Include scores in result
            
        Returns:
            List of elements (with scores if requested), or error string
        """
        pass
    
    @abstractmethod
    def scan(
        self,
        pattern: str = "*",
        count: int = 100
    ) -> list[str] | str:
        """
        Scan keys matching pattern.
        
        Note: Uses SCAN instead of KEYS for safety (non-blocking).
        
        Args:
            pattern: Key pattern (glob-style)
            count: Approximate number of keys to return per iteration
            
        Returns:
            List of matching keys, or error string
        """
        pass
    
    @abstractmethod
    def type(self, key: str) -> str:
        """
        Get the type of a key.
        
        Args:
            key: The key to check
            
        Returns:
            Type string ('string', 'hash', 'list', 'set', 'zset', 'none')
        """
        pass
    
    @abstractmethod
    def exists(self, *keys: str) -> int | str:
        """
        Check if keys exist.
        
        Args:
            keys: One or more keys to check
            
        Returns:
            Number of existing keys, or error string
        """
        pass
    
    @abstractmethod
    def ttl(self, key: str) -> int | str:
        """
        Get time to live for a key.
        
        Args:
            key: The key to check
            
        Returns:
            TTL in seconds, -1 if no expiry, -2 if key doesn't exist
        """
        pass
    
    @abstractmethod
    def dbsize(self) -> int | str:
        """
        Get the number of keys in the database.
        
        Returns:
            Key count, or error string
        """
        pass
    
    @abstractmethod
    def info(self, section: str | None = None) -> dict | str:
        """
        Get server information.
        
        Args:
            section: Specific section (optional)
            
        Returns:
            Info dict, or error string
        """
        pass
    
    @abstractmethod
    def check_connection(self) -> tuple[bool, str]:
        """
        Check if connection is working.
        
        Returns:
            (success, message) tuple
        """
        pass
    
    @abstractmethod
    def close(self) -> None:
        """Close connection and cleanup resources."""
        pass
    
    @property
    @abstractmethod
    def db_type(self) -> str:
        """Return database type identifier ('redis', etc.)."""
        pass


# =============================================================================
# Search Engine Adapter (Reserved for Elasticsearch)
# =============================================================================

class SearchEngineAdapter(ABC):
    """
    Abstract base class for search engine adapters (Elasticsearch, etc.).
    
    Reserved for future implementation.
    
    Planned methods:
    - search: Execute search query
    - list_indices: Get index names
    - get_mapping: Get index mapping
    - count: Count matching documents
    """
    
    @abstractmethod
    def connect(self) -> bool:
        pass
    
    @abstractmethod
    def search(
        self,
        index: str,
        query: dict,
        size: int = 100
    ) -> list[dict] | str:
        pass
    
    @abstractmethod
    def list_indices(self, pattern: str = "*") -> list[dict] | str:
        pass
    
    @abstractmethod
    def get_mapping(self, index: str) -> dict | str:
        pass
    
    @abstractmethod
    def check_connection(self) -> tuple[bool, str]:
        pass
    
    @abstractmethod
    def close(self) -> None:
        pass
    
    @property
    @abstractmethod
    def db_type(self) -> str:
        pass
