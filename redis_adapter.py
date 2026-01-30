"""
Redis Adapter Implementation

Provides Redis database access using redis-py driver.
Implements KeyValueStoreAdapter interface for key-value operations.

Features:
- Connection pooling with configurable pool size
- Command timeout via socket_timeout
- Support for all Redis data types (string, hash, list, set, sorted set)
- SCAN-based iteration (safer than KEYS)

Security:
- READ-ONLY operations only (GET, HGETALL, LRANGE, SMEMBERS, ZRANGE, SCAN, etc.)
- Dangerous commands are blocked (SET, DEL, FLUSHALL, CONFIG, etc.)
- Command validation in nosql_safety_checker.py

Connection Best Practices:
- Uses ConnectionPool for connection reuse
- socket_timeout for command timeout
- health_check_interval for connection validation

References:
- redis-py Documentation: https://redis-py.readthedocs.io/en/stable/
- Redis Command Reference: https://redis.io/commands/
"""

import logging
from typing import Any

from nosql_adapter import (
    KeyValueStoreAdapter,
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_PASSWORD,
    REDIS_SOCKET_TIMEOUT,
    REDIS_CONNECT_TIMEOUT,
    REDIS_MAX_CONNECTIONS,
    MAX_RESULT_KEYS,
)

logger = logging.getLogger(__name__)


class RedisAdapter(KeyValueStoreAdapter):
    """
    Redis adapter using redis-py driver.
    
    Features:
    - Connection pooling with automatic management
    - Command timeout via socket_timeout
    - Support for all Redis data types
    - SCAN-based key iteration (non-blocking)
    
    Thread Safety:
    - redis.Redis with ConnectionPool is thread-safe
    - Single instance should be shared across threads
    
    Timeout Implementation:
    - socket_timeout: Per-command timeout
    - socket_connect_timeout: Connection establishment timeout
    """
    
    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        db: int | None = None,
        password: str | None = None,
        socket_timeout: int | None = None,
        connect_timeout: int | None = None,
        max_connections: int | None = None
    ):
        """
        Initialize Redis adapter.
        
        Args:
            host: Redis host (default from REDIS_HOST env)
            port: Redis port (default from REDIS_PORT env)
            db: Redis database number (default from REDIS_DB env)
            password: Redis password (default from REDIS_PASSWORD env)
            socket_timeout: Command timeout in seconds
            connect_timeout: Connection timeout in seconds
            max_connections: Maximum pool connections
        """
        self._host = host or REDIS_HOST
        self._port = port or REDIS_PORT
        self._db = db if db is not None else REDIS_DB
        self._password = password or REDIS_PASSWORD
        self._socket_timeout = socket_timeout or REDIS_SOCKET_TIMEOUT
        self._connect_timeout = connect_timeout or REDIS_CONNECT_TIMEOUT
        self._max_connections = max_connections or REDIS_MAX_CONNECTIONS
        self._client = None
        self._pool = None
        self._connected = False
    
    @property
    def db_type(self) -> str:
        return "redis"
    
    def connect(self) -> bool:
        """
        Create Redis client with connection pool.
        
        Uses recommended production settings:
        - ConnectionPool for connection reuse
        - socket_timeout for command timeout
        - health_check_interval for connection validation
        """
        if self._client is not None:
            return True
        
        try:
            import redis
            
            # Create connection pool
            self._pool = redis.ConnectionPool(
                host=self._host,
                port=self._port,
                db=self._db,
                password=self._password,
                # Timeout settings
                socket_timeout=self._socket_timeout,
                socket_connect_timeout=self._connect_timeout,
                # Pool settings
                max_connections=self._max_connections,
                # Decode responses to strings
                decode_responses=True,
                # Health check for idle connections
                health_check_interval=30,
            )
            
            # Create Redis client
            self._client = redis.Redis(connection_pool=self._pool)
            
            # Verify connection
            self._client.ping()
            self._connected = True
            logger.info(f"Redis adapter connected to {self._host}:{self._port}/{self._db}")
            return True
            
        except ImportError:
            logger.error("redis-py not installed. Run: pip install redis")
            return False
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            return False
    
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
        logger.warning(f"Redis {operation} error: {error_str[:200]}")
        
        if "NOAUTH" in error_str or "Authentication" in error_str:
            return "Error: Redis authentication failed"
        elif "NOPERM" in error_str or "permission" in error_str.lower():
            return "Error: Not authorized for this operation"
        elif "timeout" in error_str.lower() or "timed out" in error_str.lower():
            return f"Error: Operation timeout exceeded ({self._socket_timeout}s limit)"
        elif "Connection" in error_str or "connection" in error_str.lower():
            return "Error: Redis connection failed"
        elif "WRONGTYPE" in error_str:
            return "Error: Wrong data type for this operation"
        else:
            return f"Error: Redis {operation} failed"
    
    def get(self, key: str) -> Any | str:
        """Get value for a string key."""
        if not self._client:
            if not self.connect():
                return "Error: Redis connection not available"
        
        try:
            value = self._client.get(key)
            if value is None:
                return {"key": key, "value": None, "exists": False}
            return {"key": key, "value": value, "exists": True}
            
        except Exception as e:
            return self._handle_error(e, "get")
    
    def mget(self, keys: list[str]) -> list[Any] | str:
        """Get values for multiple keys."""
        if not self._client:
            if not self.connect():
                return "Error: Redis connection not available"
        
        try:
            values = self._client.mget(keys)
            result = []
            for key, value in zip(keys, values):
                result.append({
                    "key": key,
                    "value": value,
                    "exists": value is not None
                })
            return result
            
        except Exception as e:
            return self._handle_error(e, "mget")
    
    def hgetall(self, key: str) -> dict | str:
        """Get all fields and values of a hash."""
        if not self._client:
            if not self.connect():
                return "Error: Redis connection not available"
        
        try:
            value = self._client.hgetall(key)
            return {
                "key": key,
                "type": "hash",
                "data": value,
                "field_count": len(value)
            }
            
        except Exception as e:
            return self._handle_error(e, "hgetall")
    
    def lrange(self, key: str, start: int = 0, stop: int = -1) -> list | str:
        """Get elements from a list."""
        if not self._client:
            if not self.connect():
                return "Error: Redis connection not available"
        
        try:
            values = self._client.lrange(key, start, stop)
            return {
                "key": key,
                "type": "list",
                "data": values,
                "count": len(values),
                "range": {"start": start, "stop": stop}
            }
            
        except Exception as e:
            return self._handle_error(e, "lrange")
    
    def smembers(self, key: str) -> set | str:
        """Get all members of a set."""
        if not self._client:
            if not self.connect():
                return "Error: Redis connection not available"
        
        try:
            members = self._client.smembers(key)
            return {
                "key": key,
                "type": "set",
                "data": list(members),  # Convert set to list for JSON
                "count": len(members)
            }
            
        except Exception as e:
            return self._handle_error(e, "smembers")
    
    def zrange(
        self,
        key: str,
        start: int = 0,
        stop: int = -1,
        withscores: bool = False
    ) -> list | str:
        """Get elements from a sorted set by index."""
        if not self._client:
            if not self.connect():
                return "Error: Redis connection not available"
        
        try:
            values = self._client.zrange(key, start, stop, withscores=withscores)
            
            if withscores:
                # Convert list of tuples to list of dicts
                data = [{"member": m, "score": s} for m, s in values]
            else:
                data = values
            
            return {
                "key": key,
                "type": "zset",
                "data": data,
                "count": len(values),
                "range": {"start": start, "stop": stop},
                "withscores": withscores
            }
            
        except Exception as e:
            return self._handle_error(e, "zrange")
    
    def scan(
        self,
        pattern: str = "*",
        count: int = 100
    ) -> list[str] | str:
        """
        Scan keys matching pattern.
        
        Uses SCAN iterator instead of KEYS for safety (non-blocking).
        Respects MAX_RESULT_KEYS limit for token protection.
        """
        if not self._client:
            if not self.connect():
                return "Error: Redis connection not available"
        
        try:
            keys = []
            effective_limit = min(count, MAX_RESULT_KEYS) if MAX_RESULT_KEYS > 0 else count
            
            # Use scan_iter for memory-efficient iteration
            for key in self._client.scan_iter(match=pattern, count=100):
                keys.append(key)
                if len(keys) >= effective_limit:
                    break
            
            return {
                "pattern": pattern,
                "keys": keys,
                "count": len(keys),
                "truncated": len(keys) >= effective_limit
            }
            
        except Exception as e:
            return self._handle_error(e, "scan")
    
    def type(self, key: str) -> str:
        """Get the type of a key."""
        if not self._client:
            if not self.connect():
                return "Error: Redis connection not available"
        
        try:
            key_type = self._client.type(key)
            return {
                "key": key,
                "type": key_type
            }
            
        except Exception as e:
            return self._handle_error(e, "type")
    
    def exists(self, *keys: str) -> int | str:
        """Check if keys exist."""
        if not self._client:
            if not self.connect():
                return "Error: Redis connection not available"
        
        try:
            count = self._client.exists(*keys)
            return {
                "keys": list(keys),
                "existing_count": count,
                "total_checked": len(keys)
            }
            
        except Exception as e:
            return self._handle_error(e, "exists")
    
    def ttl(self, key: str) -> int | str:
        """
        Get time to live for a key.
        
        Returns:
            TTL in seconds, -1 if no expiry, -2 if key doesn't exist
        """
        if not self._client:
            if not self.connect():
                return "Error: Redis connection not available"
        
        try:
            ttl_value = self._client.ttl(key)
            
            if ttl_value == -2:
                status = "key_not_found"
            elif ttl_value == -1:
                status = "no_expiry"
            else:
                status = "has_expiry"
            
            return {
                "key": key,
                "ttl_seconds": ttl_value,
                "status": status
            }
            
        except Exception as e:
            return self._handle_error(e, "ttl")
    
    def dbsize(self) -> int | str:
        """Get the number of keys in the database."""
        if not self._client:
            if not self.connect():
                return "Error: Redis connection not available"
        
        try:
            size = self._client.dbsize()
            return {
                "db": self._db,
                "key_count": size
            }
            
        except Exception as e:
            return self._handle_error(e, "dbsize")
    
    def info(self, section: str | None = None) -> dict | str:
        """
        Get server information.
        
        Args:
            section: Specific section (server, clients, memory, stats, etc.)
        """
        if not self._client:
            if not self.connect():
                return "Error: Redis connection not available"
        
        try:
            if section:
                info = self._client.info(section)
            else:
                # Return condensed info by default
                info = self._client.info("server")
            
            return info
            
        except Exception as e:
            return self._handle_error(e, "info")
    
    def check_connection(self) -> tuple[bool, str]:
        """Check Redis connection status."""
        if not self._client:
            if not self.connect():
                return False, "Redis connection not available"
        
        try:
            self._client.ping()
            return True, "Redis connection successful"
        except Exception as e:
            return False, self._handle_error(e, "ping")
    
    def close(self) -> None:
        """Close Redis client and connection pool."""
        if self._client:
            self._client.close()
            self._client = None
        if self._pool:
            self._pool.disconnect()
            self._pool = None
        self._connected = False
        logger.info("Redis adapter closed")


# =============================================================================
# Factory Function
# =============================================================================

_redis_adapter: RedisAdapter | None = None


def get_redis_adapter() -> RedisAdapter:
    """
    Get or create the global Redis adapter.
    
    Returns:
        The global RedisAdapter instance
    """
    global _redis_adapter
    if _redis_adapter is None:
        _redis_adapter = RedisAdapter()
        _redis_adapter.connect()
    return _redis_adapter


def reset_redis_adapter() -> None:
    """Reset the global Redis adapter."""
    global _redis_adapter
    if _redis_adapter is not None:
        _redis_adapter.close()
        _redis_adapter = None
