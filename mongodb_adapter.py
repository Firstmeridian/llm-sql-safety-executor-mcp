"""
MongoDB Adapter Implementation

Provides MongoDB database access using PyMongo driver.
Implements DocumentStoreAdapter interface for document-oriented operations.

Features:
- Connection pooling with configurable pool size
- Query timeout via timeoutMS (PyMongo 4.2+)
- Schema inference by sampling documents
- Aggregation pipeline support with safety validation

Security:
- READ-ONLY operations only (find, aggregate, count, listCollections)
- Aggregation pipeline validated by nosql_safety_checker.py
- $out and $merge stages are blocked

Connection Best Practices:
- MongoClient is thread-safe, single instance per application
- Uses timeoutMS for unified operation timeout
- Connection pooling handled internally by PyMongo

References:
- PyMongo Documentation: https://pymongo.readthedocs.io/en/stable/
- MongoDB MCP Server: https://github.com/mongodb-js/mongodb-mcp-server
"""

import logging
from typing import Any
from collections import defaultdict

from nosql_adapter import (
    DocumentStoreAdapter,
    MONGODB_URI,
    MONGODB_DATABASE,
    MONGODB_TIMEOUT_MS,
    MONGODB_MAX_POOL_SIZE,
    MAX_RESULT_DOCS,
)

logger = logging.getLogger(__name__)


class MongoDBAdapter(DocumentStoreAdapter):
    """
    MongoDB adapter using PyMongo driver.
    
    Features:
    - Connection pooling with automatic management
    - Query timeout via timeoutMS parameter
    - Schema inference by sampling documents
    - Aggregation pipeline support
    
    Thread Safety:
    - MongoClient is thread-safe
    - Single instance should be shared across threads
    
    Timeout Implementation:
    - Uses timeoutMS (PyMongo 4.2+) for unified timeout
    - Falls back to serverSelectionTimeoutMS + socketTimeoutMS for older versions
    """
    
    def __init__(
        self,
        uri: str | None = None,
        database: str | None = None,
        timeout_ms: int | None = None,
        max_pool_size: int | None = None
    ):
        """
        Initialize MongoDB adapter.
        
        Args:
            uri: MongoDB connection URI (default from MONGODB_URI env)
            database: Default database name (default from MONGODB_DATABASE env)
            timeout_ms: Operation timeout in milliseconds
            max_pool_size: Maximum connection pool size
        """
        self._uri = uri or MONGODB_URI
        self._default_database = database or MONGODB_DATABASE
        self._timeout_ms = timeout_ms or MONGODB_TIMEOUT_MS
        self._max_pool_size = max_pool_size or MONGODB_MAX_POOL_SIZE
        self._client = None
        self._connected = False
    
    @property
    def db_type(self) -> str:
        return "mongodb"
    
    @property
    def default_database(self) -> str:
        return self._default_database
    
    def connect(self) -> bool:
        """
        Create MongoDB client with connection pool.
        
        Uses recommended production settings:
        - timeoutMS for unified operation timeout
        - maxPoolSize for connection limits
        - retryWrites/retryReads for resilience
        """
        if self._client is not None:
            return True
        
        try:
            from pymongo import MongoClient
            from pymongo.errors import ConnectionFailure
            
            # Create client with recommended settings
            # Reference: PyMongo connection best practices
            self._client = MongoClient(
                self._uri,
                # Connection pool settings
                maxPoolSize=self._max_pool_size,
                minPoolSize=0,
                maxIdleTimeMS=60000,  # 60s idle timeout
                # Timeout settings (unified timeout - PyMongo 4.2+)
                timeoutMS=self._timeout_ms,
                serverSelectionTimeoutMS=self._timeout_ms,
                connectTimeoutMS=10000,  # 10s connect timeout
                # Retry settings
                retryWrites=True,
                retryReads=True,
                # Lazy connection (don't block on init)
                connect=False,
            )
            
            # Verify connection works
            self._client.admin.command('ping')
            self._connected = True
            logger.info(f"MongoDB adapter connected to {self._uri}")
            return True
            
        except ImportError:
            logger.error("PyMongo not installed. Run: pip install pymongo")
            return False
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            return False
    
    def _get_database(self, database: str | None = None):
        """Get database object."""
        db_name = database or self._default_database
        return self._client[db_name]
    
    def _handle_error(self, e: Exception, operation: str) -> str:
        """
        Sanitize error messages for security.
        
        Args:
            e: The exception
            operation: Operation name for context
            
        Returns:
            Sanitized error message
        """
        error_str = str(e)
        logger.warning(f"MongoDB {operation} error: {error_str[:200]}")
        
        if "Authentication failed" in error_str:
            return "Error: MongoDB authentication failed"
        elif "not authorized" in error_str.lower():
            return "Error: Not authorized for this operation"
        elif "timed out" in error_str.lower() or "timeout" in error_str.lower():
            return f"Error: Operation timeout exceeded ({self._timeout_ms}ms limit)"
        elif "not found" in error_str.lower() or "doesn't exist" in error_str.lower():
            return "Error: Collection or database not found"
        elif "connection" in error_str.lower():
            return "Error: MongoDB connection failed"
        else:
            return f"Error: MongoDB {operation} failed"
    
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
        
        Converts ObjectId to string for JSON serialization.
        Respects MAX_RESULT_DOCS limit for token protection.
        """
        if not self._client:
            if not self.connect():
                return "Error: MongoDB connection not available"
        
        try:
            db = self._get_database(database)
            coll = db[collection]
            
            # Apply limit cap for token protection
            effective_limit = min(limit, MAX_RESULT_DOCS) if MAX_RESULT_DOCS > 0 else limit
            
            cursor = coll.find(
                filter=filter or {},
                projection=projection,
                skip=skip,
                limit=effective_limit,
                sort=sort
            )
            
            # Convert to list and serialize ObjectId
            documents = []
            for doc in cursor:
                documents.append(self._serialize_document(doc))
            
            return documents
            
        except Exception as e:
            return self._handle_error(e, "find")
    
    def _serialize_document(self, doc: dict) -> dict:
        """
        Serialize MongoDB document for JSON.
        
        Converts:
        - ObjectId -> string
        - datetime -> ISO string
        - bytes -> hex string
        """
        from bson import ObjectId
        from datetime import datetime
        
        result = {}
        for key, value in doc.items():
            if isinstance(value, ObjectId):
                result[key] = str(value)
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, bytes):
                result[key] = value.hex()
            elif isinstance(value, dict):
                result[key] = self._serialize_document(value)
            elif isinstance(value, list):
                result[key] = [
                    self._serialize_document(v) if isinstance(v, dict)
                    else str(v) if isinstance(v, ObjectId)
                    else v
                    for v in value
                ]
            else:
                result[key] = value
        return result
    
    def aggregate(
        self,
        collection: str,
        pipeline: list[dict],
        database: str | None = None
    ) -> list[dict] | str:
        """
        Execute an aggregation pipeline.
        
        Note: Pipeline should be validated by nosql_safety_checker.py
        before calling this method. Dangerous stages are blocked there.
        """
        if not self._client:
            if not self.connect():
                return "Error: MongoDB connection not available"
        
        try:
            db = self._get_database(database)
            coll = db[collection]
            
            cursor = coll.aggregate(pipeline)
            
            # Convert to list with limit
            documents = []
            for i, doc in enumerate(cursor):
                if MAX_RESULT_DOCS > 0 and i >= MAX_RESULT_DOCS:
                    break
                documents.append(self._serialize_document(doc))
            
            return documents
            
        except Exception as e:
            return self._handle_error(e, "aggregate")
    
    def count_documents(
        self,
        collection: str,
        filter: dict | None = None,
        database: str | None = None
    ) -> int | str:
        """Count documents matching filter."""
        if not self._client:
            if not self.connect():
                return "Error: MongoDB connection not available"
        
        try:
            db = self._get_database(database)
            coll = db[collection]
            
            count = coll.count_documents(filter or {})
            return count
            
        except Exception as e:
            return self._handle_error(e, "count_documents")
    
    def list_databases(self) -> list[str] | str:
        """List all accessible databases."""
        if not self._client:
            if not self.connect():
                return "Error: MongoDB connection not available"
        
        try:
            # Filter out system databases
            databases = []
            for db_info in self._client.list_databases():
                name = db_info['name']
                if name not in ('admin', 'config', 'local'):
                    databases.append(name)
            
            return sorted(databases)
            
        except Exception as e:
            return self._handle_error(e, "list_databases")
    
    def list_collections(self, database: str | None = None) -> list[dict] | str:
        """
        List collections with document counts.
        
        Returns list of dicts with 'name' and 'document_count' keys.
        """
        if not self._client:
            if not self.connect():
                return "Error: MongoDB connection not available"
        
        try:
            db = self._get_database(database)
            
            collections = []
            for name in db.list_collection_names():
                # Skip system collections
                if name.startswith('system.'):
                    continue
                
                # Get estimated document count (fast)
                try:
                    count = db[name].estimated_document_count()
                except Exception:
                    count = 0
                
                collections.append({
                    "name": name,
                    "document_count": count
                })
            
            return sorted(collections, key=lambda x: x['name'])
            
        except Exception as e:
            return self._handle_error(e, "list_collections")
    
    def get_collection_schema(
        self,
        collection: str,
        sample_size: int = 100,
        database: str | None = None
    ) -> dict | str:
        """
        Infer collection schema by sampling documents.
        
        Returns schema dict with field names, types, and occurrence counts.
        
        Note: MongoDB is schema-less, this is an approximation based on samples.
        """
        if not self._client:
            if not self.connect():
                return "Error: MongoDB connection not available"
        
        try:
            db = self._get_database(database)
            coll = db[collection]
            
            # Sample documents
            pipeline = [{"$sample": {"size": sample_size}}]
            cursor = coll.aggregate(pipeline)
            
            # Analyze field types
            field_types = defaultdict(lambda: defaultdict(int))
            total_docs = 0
            
            for doc in cursor:
                total_docs += 1
                self._analyze_document_schema(doc, field_types, "")
            
            # Build schema result
            schema = {
                "collection": collection,
                "database": database or self._default_database,
                "sample_size": total_docs,
                "fields": {}
            }
            
            for field_path, type_counts in field_types.items():
                # Find most common type
                types = sorted(type_counts.items(), key=lambda x: -x[1])
                schema["fields"][field_path] = {
                    "types": [{"type": t, "count": c} for t, c in types],
                    "occurrence": sum(type_counts.values())
                }
            
            return schema
            
        except Exception as e:
            return self._handle_error(e, "get_collection_schema")
    
    def _analyze_document_schema(
        self,
        doc: dict,
        field_types: dict,
        prefix: str
    ) -> None:
        """Recursively analyze document structure."""
        from bson import ObjectId
        from datetime import datetime
        
        for key, value in doc.items():
            field_path = f"{prefix}.{key}" if prefix else key
            
            # Determine type
            if value is None:
                type_name = "null"
            elif isinstance(value, bool):
                type_name = "boolean"
            elif isinstance(value, int):
                type_name = "int"
            elif isinstance(value, float):
                type_name = "double"
            elif isinstance(value, str):
                type_name = "string"
            elif isinstance(value, ObjectId):
                type_name = "objectId"
            elif isinstance(value, datetime):
                type_name = "date"
            elif isinstance(value, bytes):
                type_name = "binData"
            elif isinstance(value, list):
                type_name = "array"
                # Optionally analyze array element types
            elif isinstance(value, dict):
                type_name = "object"
                # Recursively analyze nested objects
                self._analyze_document_schema(value, field_types, field_path)
            else:
                type_name = type(value).__name__
            
            field_types[field_path][type_name] += 1
    
    def check_connection(self) -> tuple[bool, str]:
        """Check MongoDB connection status."""
        if not self._client:
            if not self.connect():
                return False, "MongoDB connection not available"
        
        try:
            self._client.admin.command('ping')
            return True, "MongoDB connection successful"
        except Exception as e:
            return False, self._handle_error(e, "ping")
    
    def get_server_info(self) -> dict | str:
        """Get MongoDB server information."""
        if not self._client:
            if not self.connect():
                return "Error: MongoDB connection not available"
        
        try:
            info = self._client.server_info()
            return {
                "version": info.get("version", "unknown"),
                "git_version": info.get("gitVersion", "unknown"),
                "ok": info.get("ok", 0),
            }
        except Exception as e:
            return self._handle_error(e, "server_info")
    
    def close(self) -> None:
        """Close MongoDB client."""
        if self._client:
            self._client.close()
            self._client = None
            self._connected = False
            logger.info("MongoDB adapter closed")


# =============================================================================
# Factory Function
# =============================================================================

_mongodb_adapter: MongoDBAdapter | None = None


def get_mongodb_adapter() -> MongoDBAdapter:
    """
    Get or create the global MongoDB adapter.
    
    Returns:
        The global MongoDBAdapter instance
    """
    global _mongodb_adapter
    if _mongodb_adapter is None:
        _mongodb_adapter = MongoDBAdapter()
        _mongodb_adapter.connect()
    return _mongodb_adapter


def reset_mongodb_adapter() -> None:
    """Reset the global MongoDB adapter."""
    global _mongodb_adapter
    if _mongodb_adapter is not None:
        _mongodb_adapter.close()
        _mongodb_adapter = None
