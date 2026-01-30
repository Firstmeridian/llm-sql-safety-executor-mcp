"""
NoSQL Tools for MCP Server

Provides MongoDB and Redis read-only query tools for MCP protocol.
These tools are dynamically registered based on ENABLED_DATASOURCES configuration.

MongoDB Tools:
- mongo_find: Query documents with filter
- mongo_aggregate: Run aggregation pipeline
- mongo_count: Count documents
- mongo_list_databases: List databases
- mongo_list_collections: List collections
- mongo_get_schema: Infer collection schema

Redis Tools:
- redis_get: Get string value
- redis_hgetall: Get hash
- redis_lrange: Get list range
- redis_smembers: Get set members
- redis_zrange: Get sorted set range
- redis_scan: Scan keys by pattern
- redis_type: Get key type
- redis_info: Get server info

Usage:
    from nosql_tools import register_nosql_tools
    register_nosql_tools(mcp)

Security:
- All operations are READ-ONLY
- Query validation via nosql_safety_checker
- Result size limits for token optimization
"""

import json
import logging
from typing import Any

from fastmcp import FastMCP, Context

from adapter_manager import get_adapter_manager, is_datasource_enabled
from nosql_safety_checker import (
    is_mongodb_query_safe,
    is_mongodb_pipeline_safe,
)
from nosql_adapter import MAX_RESULT_DOCS, MAX_RESULT_KEYS

logger = logging.getLogger(__name__)


def _convert_sort_to_list(sort: dict | list | None) -> list[tuple[str, int]] | None:
    """
    Convert sort specification to PyMongo format.
    
    Accepts:
    - dict: {"field": 1, "other": -1} -> [("field", 1), ("other", -1)]
    - list: [("field", 1)] -> pass through
    - None: -> None
    """
    if sort is None:
        return None
    if isinstance(sort, list):
        return sort
    if isinstance(sort, dict):
        return [(k, v) for k, v in sort.items()]
    return None


def _validate_mongo_identifier(name: str, identifier_type: str = "name") -> tuple[bool, str | None]:
    """
    Validate MongoDB database/collection name.
    
    MongoDB naming rules:
    - Cannot be empty
    - Cannot contain: / \\ . " $ * < > : | ?
    - Cannot start with 'system.' (reserved)
    - Max 120 characters for database, 255 for collection
    
    Security:
    - Prevents path traversal attacks
    - Prevents injection via special characters
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name:
        return False, f"Invalid {identifier_type}: cannot be empty"
    
    if len(name) > 255:
        return False, f"Invalid {identifier_type}: too long (max 255 characters)"
    
    # Forbidden characters (security + MongoDB rules)
    forbidden_chars = set('/\\."$*<>:|?\x00')
    if any(c in forbidden_chars for c in name):
        return False, f"Invalid {identifier_type}: contains forbidden characters"
    
    # Prevent access to system collections
    if name.lower().startswith("system."):
        return False, f"Invalid {identifier_type}: cannot access system namespace"
    
    # Prevent path traversal
    if ".." in name or name.startswith(".") or name.endswith("."):
        return False, f"Invalid {identifier_type}: invalid format"
    
    return True, None


def _validate_redis_key(key: str) -> tuple[bool, str | None]:
    """
    Validate Redis key for security.
    
    Redis key rules:
    - Cannot be empty
    - Max 512 MB (we limit to 1024 chars for sanity)
    - Block control characters that could cause issues
    
    Security:
    - Prevent excessively long keys (DoS)
    - Block null bytes and control characters
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not key:
        return False, "Invalid key: cannot be empty"
    
    if len(key) > 1024:
        return False, "Invalid key: too long (max 1024 characters)"
    
    # Block control characters (0x00-0x1F except tab/newline which are rare but valid)
    # Null byte is the main concern for injection
    if '\x00' in key:
        return False, "Invalid key: contains null byte"
    
    return True, None


# =============================================================================
# MongoDB Tools
# =============================================================================

def register_mongodb_tools(mcp: FastMCP) -> None:
    """
    Register MongoDB tools with the MCP server.
    
    Only registers if MongoDB is enabled in ENABLED_DATASOURCES.
    """
    if not is_datasource_enabled("mongodb"):
        logger.info("MongoDB not in ENABLED_DATASOURCES, skipping tool registration")
        return
    
    logger.info("Registering MongoDB tools...")
    
    @mcp.tool(
        name="mongo_find",
        description="""Query MongoDB documents with filter and options.

Args:
    database: Database name
    collection: Collection name
    filter: Query filter (MongoDB query syntax)
    projection: Fields to include/exclude (optional)
    limit: Maximum documents to return (default: 100)
    sort: Sort specification (optional)

Returns documents matching the filter."""
    )
    async def mongo_find(
        database: str,
        collection: str,
        filter: dict | None = None,
        projection: dict | None = None,
        limit: int = 100,
        sort: dict | None = None,
        ctx: Context = None
    ) -> dict[str, Any]:
        """Execute MongoDB find query."""
        adapter = get_adapter_manager().get_mongodb_adapter()
        if not adapter:
            return {"success": False, "error": "MongoDB adapter not available"}
        
        # Validate database and collection names
        valid, err = _validate_mongo_identifier(database, "database")
        if not valid:
            return {"success": False, "error": err}
        valid, err = _validate_mongo_identifier(collection, "collection")
        if not valid:
            return {"success": False, "error": err}
        
        # Validate filter
        if filter:
            is_safe, msg = is_mongodb_query_safe(filter)
            if not is_safe:
                if ctx:
                    await ctx.warning(f"Query blocked: {msg}")
                return {"success": False, "error": msg}
        
        # Apply limit
        effective_limit = min(limit, MAX_RESULT_DOCS) if MAX_RESULT_DOCS > 0 else limit
        
        if ctx:
            await ctx.info(f"MongoDB find: {database}.{collection}")
        
        result = adapter.find(
            database=database,
            collection=collection,
            filter=filter or {},
            projection=projection,
            limit=effective_limit,
            sort=_convert_sort_to_list(sort)
        )
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {
            "success": True,
            "database": database,
            "collection": collection,
            "documents": result,
            "count": len(result),
            "truncated": len(result) >= effective_limit
        }
    
    @mcp.tool(
        name="mongo_aggregate",
        description="""Run MongoDB aggregation pipeline.

Args:
    database: Database name
    collection: Collection name
    pipeline: Aggregation pipeline stages (list of stage objects)

Returns aggregation results. Blocked stages: $out, $merge (write operations)."""
    )
    async def mongo_aggregate(
        database: str,
        collection: str,
        pipeline: list,
        ctx: Context = None
    ) -> dict[str, Any]:
        """Execute MongoDB aggregation pipeline."""
        adapter = get_adapter_manager().get_mongodb_adapter()
        if not adapter:
            return {"success": False, "error": "MongoDB adapter not available"}
        
        # Validate database and collection names
        valid, err = _validate_mongo_identifier(database, "database")
        if not valid:
            return {"success": False, "error": err}
        valid, err = _validate_mongo_identifier(collection, "collection")
        if not valid:
            return {"success": False, "error": err}
        
        # Validate pipeline
        is_safe, msg = is_mongodb_pipeline_safe(pipeline)
        if not is_safe:
            if ctx:
                await ctx.warning(f"Pipeline blocked: {msg}")
            return {"success": False, "error": msg}
        
        if ctx:
            await ctx.info(f"MongoDB aggregate: {database}.{collection}")
        
        result = adapter.aggregate(
            database=database,
            collection=collection,
            pipeline=pipeline
        )
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {
            "success": True,
            "database": database,
            "collection": collection,
            "results": result,
            "count": len(result)
        }
    
    @mcp.tool(
        name="mongo_count",
        description="""Count documents in MongoDB collection.

Args:
    database: Database name
    collection: Collection name
    filter: Query filter (optional, count all if not provided)

Returns document count."""
    )
    async def mongo_count(
        database: str,
        collection: str,
        filter: dict | None = None,
        ctx: Context = None
    ) -> dict[str, Any]:
        """Count MongoDB documents."""
        adapter = get_adapter_manager().get_mongodb_adapter()
        if not adapter:
            return {"success": False, "error": "MongoDB adapter not available"}
        
        # Validate database and collection names
        valid, err = _validate_mongo_identifier(database, "database")
        if not valid:
            return {"success": False, "error": err}
        valid, err = _validate_mongo_identifier(collection, "collection")
        if not valid:
            return {"success": False, "error": err}
        
        # Validate filter
        if filter:
            is_safe, msg = is_mongodb_query_safe(filter)
            if not is_safe:
                if ctx:
                    await ctx.warning(f"Query blocked: {msg}")
                return {"success": False, "error": msg}
        
        if ctx:
            await ctx.info(f"MongoDB count: {database}.{collection}")
        
        result = adapter.count_documents(
            database=database,
            collection=collection,
            filter=filter or {}
        )
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {
            "success": True,
            "database": database,
            "collection": collection,
            "count": result
        }
    
    @mcp.tool(
        name="mongo_list_databases",
        description="""List MongoDB databases.

Returns list of database names with size information.
System databases (admin, config, local) are excluded by default."""
    )
    async def mongo_list_databases(ctx: Context = None) -> dict[str, Any]:
        """List MongoDB databases."""
        adapter = get_adapter_manager().get_mongodb_adapter()
        if not adapter:
            return {"success": False, "error": "MongoDB adapter not available"}
        
        if ctx:
            await ctx.info("Listing MongoDB databases")
        
        result = adapter.list_databases()
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {
            "success": True,
            "databases": result,
            "count": len(result)
        }
    
    @mcp.tool(
        name="mongo_list_collections",
        description="""List collections in a MongoDB database.

Args:
    database: Database name

Returns collection names with document counts."""
    )
    async def mongo_list_collections(
        database: str,
        ctx: Context = None
    ) -> dict[str, Any]:
        """List MongoDB collections."""
        adapter = get_adapter_manager().get_mongodb_adapter()
        if not adapter:
            return {"success": False, "error": "MongoDB adapter not available"}
        
        # Validate database name
        valid, err = _validate_mongo_identifier(database, "database")
        if not valid:
            return {"success": False, "error": err}
        
        if ctx:
            await ctx.info(f"Listing collections in: {database}")
        
        result = adapter.list_collections(database)
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {
            "success": True,
            "database": database,
            "collections": result,
            "count": len(result)
        }
    
    @mcp.tool(
        name="mongo_get_schema",
        description="""Infer collection schema from sample documents.

Args:
    database: Database name
    collection: Collection name
    sample_size: Number of documents to sample (default: 100)

Returns inferred field types based on document sampling."""
    )
    async def mongo_get_schema(
        database: str,
        collection: str,
        sample_size: int = 100,
        ctx: Context = None
    ) -> dict[str, Any]:
        """Get MongoDB collection schema."""
        adapter = get_adapter_manager().get_mongodb_adapter()
        if not adapter:
            return {"success": False, "error": "MongoDB adapter not available"}
        
        # Validate database and collection names
        valid, err = _validate_mongo_identifier(database, "database")
        if not valid:
            return {"success": False, "error": err}
        valid, err = _validate_mongo_identifier(collection, "collection")
        if not valid:
            return {"success": False, "error": err}
        
        if ctx:
            await ctx.info(f"Inferring schema: {database}.{collection}")
        
        result = adapter.get_collection_schema(
            database=database,
            collection=collection,
            sample_size=sample_size
        )
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {
            "success": True,
            "database": database,
            "collection": collection,
            "schema": result
        }
    
    logger.info("MongoDB tools registered successfully")


# =============================================================================
# Redis Tools
# =============================================================================

def register_redis_tools(mcp: FastMCP) -> None:
    """
    Register Redis tools with the MCP server.
    
    Only registers if Redis is enabled in ENABLED_DATASOURCES.
    """
    if not is_datasource_enabled("redis"):
        logger.info("Redis not in ENABLED_DATASOURCES, skipping tool registration")
        return
    
    logger.info("Registering Redis tools...")
    
    @mcp.tool(
        name="redis_get",
        description="""Get value for a Redis string key.

Args:
    key: The key name

Returns the value or null if key doesn't exist."""
    )
    async def redis_get(key: str, ctx: Context = None) -> dict[str, Any]:
        """Get Redis string value."""
        adapter = get_adapter_manager().get_redis_adapter()
        if not adapter:
            return {"success": False, "error": "Redis adapter not available"}
        
        # Validate key
        valid, err = _validate_redis_key(key)
        if not valid:
            return {"success": False, "error": err}
        
        if ctx:
            await ctx.info(f"Redis GET: {key}")
        
        result = adapter.get(key)
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {"success": True, **result}
    
    @mcp.tool(
        name="redis_mget",
        description="""Get values for multiple Redis keys.

Args:
    keys: List of key names

Returns values for all keys (null for non-existent keys)."""
    )
    async def redis_mget(keys: list[str], ctx: Context = None) -> dict[str, Any]:
        """Get multiple Redis values."""
        adapter = get_adapter_manager().get_redis_adapter()
        if not adapter:
            return {"success": False, "error": "Redis adapter not available"}
        
        # Validate all keys
        for key in keys:
            valid, err = _validate_redis_key(key)
            if not valid:
                return {"success": False, "error": f"Key '{key[:50]}...': {err}"}
        
        if ctx:
            await ctx.info(f"Redis MGET: {len(keys)} keys")
        
        result = adapter.mget(keys)
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {"success": True, "results": result}
    
    @mcp.tool(
        name="redis_hgetall",
        description="""Get all fields and values of a Redis hash.

Args:
    key: The hash key name

Returns all field-value pairs in the hash."""
    )
    async def redis_hgetall(key: str, ctx: Context = None) -> dict[str, Any]:
        """Get Redis hash."""
        valid, error = _validate_redis_key(key)
        if not valid:
            return {"success": False, "error": error}
        
        adapter = get_adapter_manager().get_redis_adapter()
        if not adapter:
            return {"success": False, "error": "Redis adapter not available"}
        
        if ctx:
            await ctx.info(f"Redis HGETALL: {key}")
        
        result = adapter.hgetall(key)
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {"success": True, **result}
    
    @mcp.tool(
        name="redis_lrange",
        description="""Get elements from a Redis list.

Args:
    key: The list key name
    start: Start index (0-based, default: 0)
    stop: Stop index (inclusive, -1 for end, default: -1)

Returns list elements in the specified range."""
    )
    async def redis_lrange(
        key: str,
        start: int = 0,
        stop: int = -1,
        ctx: Context = None
    ) -> dict[str, Any]:
        """Get Redis list range."""
        valid, error = _validate_redis_key(key)
        if not valid:
            return {"success": False, "error": error}
        
        adapter = get_adapter_manager().get_redis_adapter()
        if not adapter:
            return {"success": False, "error": "Redis adapter not available"}
        
        if ctx:
            await ctx.info(f"Redis LRANGE: {key}[{start}:{stop}]")
        
        result = adapter.lrange(key, start, stop)
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {"success": True, **result}
    
    @mcp.tool(
        name="redis_smembers",
        description="""Get all members of a Redis set.

Args:
    key: The set key name

Returns all members of the set."""
    )
    async def redis_smembers(key: str, ctx: Context = None) -> dict[str, Any]:
        """Get Redis set members."""
        valid, error = _validate_redis_key(key)
        if not valid:
            return {"success": False, "error": error}
        
        adapter = get_adapter_manager().get_redis_adapter()
        if not adapter:
            return {"success": False, "error": "Redis adapter not available"}
        
        if ctx:
            await ctx.info(f"Redis SMEMBERS: {key}")
        
        result = adapter.smembers(key)
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {"success": True, **result}
    
    @mcp.tool(
        name="redis_zrange",
        description="""Get elements from a Redis sorted set by index.

Args:
    key: The sorted set key name
    start: Start index (0-based, default: 0)
    stop: Stop index (inclusive, -1 for end, default: -1)
    withscores: Include scores in output (default: False)

Returns sorted set members in rank order."""
    )
    async def redis_zrange(
        key: str,
        start: int = 0,
        stop: int = -1,
        withscores: bool = False,
        ctx: Context = None
    ) -> dict[str, Any]:
        """Get Redis sorted set range."""
        valid, error = _validate_redis_key(key)
        if not valid:
            return {"success": False, "error": error}
        
        adapter = get_adapter_manager().get_redis_adapter()
        if not adapter:
            return {"success": False, "error": "Redis adapter not available"}
        
        if ctx:
            await ctx.info(f"Redis ZRANGE: {key}[{start}:{stop}]")
        
        result = adapter.zrange(key, start, stop, withscores)
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {"success": True, **result}
    
    @mcp.tool(
        name="redis_scan",
        description="""Scan Redis keys matching a pattern.

Args:
    pattern: Key pattern (e.g., "user:*", "*:cache")
    count: Hint for number of keys per iteration (default: 100)

Returns matching keys. Uses SCAN (non-blocking) instead of KEYS."""
    )
    async def redis_scan(
        pattern: str = "*",
        count: int = 100,
        ctx: Context = None
    ) -> dict[str, Any]:
        """Scan Redis keys."""
        adapter = get_adapter_manager().get_redis_adapter()
        if not adapter:
            return {"success": False, "error": "Redis adapter not available"}
        
        if ctx:
            await ctx.info(f"Redis SCAN: pattern={pattern}")
        
        result = adapter.scan(pattern, count)
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {"success": True, **result}
    
    @mcp.tool(
        name="redis_type",
        description="""Get the data type of a Redis key.

Args:
    key: The key name

Returns type: string, hash, list, set, zset, stream, or none."""
    )
    async def redis_type(key: str, ctx: Context = None) -> dict[str, Any]:
        """Get Redis key type."""
        valid, error = _validate_redis_key(key)
        if not valid:
            return {"success": False, "error": error}
        
        adapter = get_adapter_manager().get_redis_adapter()
        if not adapter:
            return {"success": False, "error": "Redis adapter not available"}
        
        if ctx:
            await ctx.info(f"Redis TYPE: {key}")
        
        result = adapter.type(key)
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {"success": True, **result}
    
    @mcp.tool(
        name="redis_exists",
        description="""Check if Redis keys exist.

Args:
    keys: One or more key names to check

Returns count of existing keys."""
    )
    async def redis_exists(keys: list[str], ctx: Context = None) -> dict[str, Any]:
        """Check Redis key existence."""
        for key in keys:
            valid, error = _validate_redis_key(key)
            if not valid:
                return {"success": False, "error": error}
        
        adapter = get_adapter_manager().get_redis_adapter()
        if not adapter:
            return {"success": False, "error": "Redis adapter not available"}
        
        if ctx:
            await ctx.info(f"Redis EXISTS: {len(keys)} keys")
        
        result = adapter.exists(*keys)
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {"success": True, **result}
    
    @mcp.tool(
        name="redis_ttl",
        description="""Get time-to-live for a Redis key.

Args:
    key: The key name

Returns TTL in seconds, -1 if no expiry, -2 if key doesn't exist."""
    )
    async def redis_ttl(key: str, ctx: Context = None) -> dict[str, Any]:
        """Get Redis key TTL."""
        valid, error = _validate_redis_key(key)
        if not valid:
            return {"success": False, "error": error}
        
        adapter = get_adapter_manager().get_redis_adapter()
        if not adapter:
            return {"success": False, "error": "Redis adapter not available"}
        
        if ctx:
            await ctx.info(f"Redis TTL: {key}")
        
        result = adapter.ttl(key)
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {"success": True, **result}
    
    @mcp.tool(
        name="redis_dbsize",
        description="""Get the number of keys in the current Redis database.

Returns total key count."""
    )
    async def redis_dbsize(ctx: Context = None) -> dict[str, Any]:
        """Get Redis database size."""
        adapter = get_adapter_manager().get_redis_adapter()
        if not adapter:
            return {"success": False, "error": "Redis adapter not available"}
        
        if ctx:
            await ctx.info("Redis DBSIZE")
        
        result = adapter.dbsize()
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {"success": True, **result}
    
    @mcp.tool(
        name="redis_info",
        description="""Get Redis server information.

Args:
    section: Info section (server, clients, memory, stats, etc.)

Returns server information for the specified section."""
    )
    async def redis_info(
        section: str | None = None,
        ctx: Context = None
    ) -> dict[str, Any]:
        """Get Redis server info."""
        adapter = get_adapter_manager().get_redis_adapter()
        if not adapter:
            return {"success": False, "error": "Redis adapter not available"}
        
        if ctx:
            await ctx.info(f"Redis INFO: {section or 'server'}")
        
        result = adapter.info(section)
        
        if isinstance(result, str) and result.startswith("Error:"):
            return {"success": False, "error": result}
        
        return {"success": True, "info": result}
    
    logger.info("Redis tools registered successfully")


# =============================================================================
# Registration Function
# =============================================================================

def register_nosql_tools(mcp: FastMCP) -> None:
    """
    Register all NoSQL tools with the MCP server.
    
    Only registers tools for datasources that are enabled in ENABLED_DATASOURCES.
    
    Args:
        mcp: FastMCP server instance
    """
    logger.info("Registering NoSQL tools...")
    
    register_mongodb_tools(mcp)
    register_redis_tools(mcp)
    
    logger.info("NoSQL tool registration complete")
