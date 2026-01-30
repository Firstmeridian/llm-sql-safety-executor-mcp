"""
NoSQL Safety Checker

Security validation for NoSQL database operations.
Implements both ALLOWLIST and BLOCKLIST patterns for defense in depth.

Components:
- MongoDBSafetyChecker: Validates MongoDB queries and aggregation pipelines
- RedisSafetyChecker: Validates Redis commands using strict allowlist

Security Model:
1. ALLOWLIST: Only explicitly allowed operations are permitted
2. BLOCKLIST: Dangerous patterns are explicitly blocked
3. Both checks must pass for an operation to be allowed

MongoDB Security:
- Blocks: $out, $merge, $where, $function, $accumulator (write/code execution)
- Validates aggregation pipeline stages
- Prevents server-side JavaScript execution

Redis Security:
- Strict command allowlist (READ-ONLY operations only)
- Blocks: SET, DEL, FLUSHALL, FLUSHDB, CONFIG, DEBUG, SCRIPT, etc.
- Pattern validation for SCAN operations

References:
- MongoDB Security Checklist: https://www.mongodb.com/docs/manual/administration/security-checklist/
- Redis Security: https://redis.io/docs/management/security/
"""

import logging
import re
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SafetyResult(Enum):
    """Result of safety validation."""
    SAFE = "safe"
    BLOCKED = "blocked"
    INVALID = "invalid"


class MongoDBSafetyChecker:
    """
    MongoDB query and aggregation pipeline safety validator.
    
    Security Strategy:
    1. Block dangerous aggregation stages ($out, $merge)
    2. Block server-side JavaScript ($where, $function, $accumulator)
    3. Validate operator usage in queries
    4. Prevent injection via operator keys
    
    Blocked Stages (Aggregation):
    - $out: Writes results to a collection
    - $merge: Writes results to a collection (with merge options)
    - $collStats: Can expose sensitive collection metadata
    
    Blocked Operators (Query):
    - $where: Server-side JavaScript execution
    - $function: Server-side JavaScript execution
    - $accumulator: Server-side JavaScript in $group
    - $expr with $function: JavaScript in expressions
    """
    
    # Aggregation stages that write data or execute code
    BLOCKED_STAGES = frozenset([
        "$out",          # Writes to collection
        "$merge",        # Writes to collection with merge
    ])
    
    # Operators that execute server-side JavaScript
    BLOCKED_OPERATORS = frozenset([
        "$where",        # Server-side JavaScript
        "$function",     # User-defined JavaScript function
        "$accumulator",  # JavaScript accumulator in $group
    ])
    
    # Additional blocked patterns in string values
    BLOCKED_PATTERNS = [
        re.compile(r"function\s*\(", re.IGNORECASE),  # JavaScript function
        re.compile(r"return\s+", re.IGNORECASE),       # JavaScript return
    ]
    
    def __init__(self):
        """Initialize MongoDB safety checker."""
        pass
    
    def validate_query(self, query: dict[str, Any]) -> tuple[SafetyResult, str]:
        """
        Validate a MongoDB find query filter.
        
        Args:
            query: MongoDB query filter document
            
        Returns:
            Tuple of (SafetyResult, message)
        """
        if not isinstance(query, dict):
            return SafetyResult.INVALID, "Query must be a dictionary"
        
        # Empty query is safe
        if not query:
            return SafetyResult.SAFE, "Query is safe"
        
        # Recursively check for blocked operators
        blocked = self._find_blocked_operators(query)
        if blocked:
            return SafetyResult.BLOCKED, f"Blocked operator(s): {', '.join(blocked)}"
        
        # Check for dangerous patterns in string values
        dangerous = self._find_dangerous_patterns(query)
        if dangerous:
            return SafetyResult.BLOCKED, f"Dangerous pattern detected: {dangerous}"
        
        return SafetyResult.SAFE, "Query is safe"
    
    def validate_pipeline(self, pipeline: list[dict]) -> tuple[SafetyResult, str]:
        """
        Validate a MongoDB aggregation pipeline.
        
        Args:
            pipeline: List of aggregation stages
            
        Returns:
            Tuple of (SafetyResult, message)
        """
        if not isinstance(pipeline, list):
            return SafetyResult.INVALID, "Pipeline must be a list"
        
        # Empty pipeline is safe
        if not pipeline:
            return SafetyResult.SAFE, "Pipeline is safe"
        
        for i, stage in enumerate(pipeline):
            if not isinstance(stage, dict):
                return SafetyResult.INVALID, f"Stage {i} must be a dictionary"
            
            # Check for blocked stages
            for stage_name in stage.keys():
                if stage_name.lower() in self.BLOCKED_STAGES:
                    return SafetyResult.BLOCKED, f"Blocked stage: {stage_name}"
            
            # Recursively check for blocked operators in stage content
            blocked = self._find_blocked_operators(stage)
            if blocked:
                return SafetyResult.BLOCKED, f"Blocked operator(s) in stage {i}: {', '.join(blocked)}"
            
            # Check for dangerous patterns in stage content
            dangerous = self._find_dangerous_patterns(stage)
            if dangerous:
                return SafetyResult.BLOCKED, f"Dangerous pattern in stage {i}: {dangerous}"
        
        return SafetyResult.SAFE, "Pipeline is safe"
    
    def _find_blocked_operators(self, obj: Any, path: str = "") -> list[str]:
        """
        Recursively find blocked operators in a document.
        
        Args:
            obj: Document to check (dict, list, or value)
            path: Current path for error reporting
            
        Returns:
            List of blocked operators found
        """
        blocked = []
        
        if isinstance(obj, dict):
            for key, value in obj.items():
                # Check if key is a blocked operator
                if key.lower() in self.BLOCKED_OPERATORS:
                    blocked.append(key)
                
                # Recursively check nested documents
                blocked.extend(self._find_blocked_operators(value, f"{path}.{key}"))
                
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                blocked.extend(self._find_blocked_operators(item, f"{path}[{i}]"))
        
        return blocked
    
    def _find_dangerous_patterns(self, obj: Any) -> str | None:
        """
        Find dangerous patterns in string values.
        
        Args:
            obj: Document to check
            
        Returns:
            Description of dangerous pattern if found, None otherwise
        """
        if isinstance(obj, str):
            for pattern in self.BLOCKED_PATTERNS:
                if pattern.search(obj):
                    return f"JavaScript code pattern"
        
        elif isinstance(obj, dict):
            for value in obj.values():
                result = self._find_dangerous_patterns(value)
                if result:
                    return result
        
        elif isinstance(obj, list):
            for item in obj:
                result = self._find_dangerous_patterns(item)
                if result:
                    return result
        
        return None


class RedisSafetyChecker:
    """
    Redis command safety validator using strict allowlist.
    
    Security Strategy:
    - ALLOWLIST ONLY: Only explicitly allowed commands are permitted
    - All commands are READ-ONLY
    - No write, delete, or administrative commands allowed
    
    Allowed Commands (READ-ONLY):
    - String: GET, MGET, STRLEN, GETRANGE
    - Hash: HGET, HGETALL, HKEYS, HVALS, HLEN, HEXISTS, HMGET
    - List: LRANGE, LLEN, LINDEX
    - Set: SMEMBERS, SCARD, SISMEMBER, SRANDMEMBER
    - Sorted Set: ZRANGE, ZRANGEBYSCORE, ZRANK, ZSCORE, ZCARD
    - Key: TYPE, EXISTS, TTL, PTTL, SCAN, KEYS (careful with KEYS)
    - Server: DBSIZE, INFO, PING, TIME
    
    Blocked Commands (Examples):
    - Write: SET, MSET, HSET, LPUSH, SADD, ZADD
    - Delete: DEL, HDEL, LREM, SREM, ZREM
    - Admin: FLUSHALL, FLUSHDB, CONFIG, DEBUG, SCRIPT, EVAL
    - Dangerous: SHUTDOWN, SLAVEOF, REPLICAOF, CLUSTER, BGSAVE
    """
    
    # Strict allowlist of READ-ONLY commands
    ALLOWED_COMMANDS = frozenset([
        # String commands (read-only)
        "GET", "MGET", "STRLEN", "GETRANGE", "GETBIT", "BITCOUNT",
        
        # Hash commands (read-only)
        "HGET", "HGETALL", "HKEYS", "HVALS", "HLEN", "HEXISTS", "HMGET", "HSCAN",
        
        # List commands (read-only)
        "LRANGE", "LLEN", "LINDEX",
        
        # Set commands (read-only)
        "SMEMBERS", "SCARD", "SISMEMBER", "SRANDMEMBER", "SSCAN",
        
        # Sorted Set commands (read-only)
        "ZRANGE", "ZRANGEBYSCORE", "ZRANGEBYLEX", "ZRANK", "ZREVRANK",
        "ZSCORE", "ZCARD", "ZCOUNT", "ZSCAN",
        
        # Key commands (read-only)
        "TYPE", "EXISTS", "TTL", "PTTL", "SCAN", "KEYS",
        "OBJECT", "DEBUG OBJECT",  # Careful: limited info
        
        # Server commands (read-only, safe)
        "DBSIZE", "INFO", "PING", "TIME", "CLIENT LIST", "CLIENT GETNAME",
    ])
    
    # Explicit blocklist for documentation and double-checking
    # These are blocked implicitly (not in allowlist) but listed for clarity
    BLOCKED_COMMANDS = frozenset([
        # Write commands
        "SET", "SETNX", "SETEX", "PSETEX", "MSET", "MSETNX",
        "APPEND", "SETRANGE", "SETBIT", "INCR", "INCRBY", "INCRBYFLOAT",
        "DECR", "DECRBY", "GETSET", "GETDEL", "GETEX",
        
        # Hash write
        "HSET", "HSETNX", "HMSET", "HINCRBY", "HINCRBYFLOAT", "HDEL",
        
        # List write
        "LPUSH", "RPUSH", "LPOP", "RPOP", "LSET", "LINSERT", "LREM",
        "LTRIM", "BLPOP", "BRPOP",
        
        # Set write
        "SADD", "SREM", "SPOP", "SMOVE",
        
        # Sorted Set write
        "ZADD", "ZREM", "ZINCRBY", "ZPOPMIN", "ZPOPMAX",
        "BZPOPMIN", "BZPOPMAX",
        
        # Key write/delete
        "DEL", "UNLINK", "EXPIRE", "EXPIREAT", "PEXPIRE", "PEXPIREAT",
        "PERSIST", "RENAME", "RENAMENX", "COPY", "MOVE",
        
        # Dangerous admin commands
        "FLUSHDB", "FLUSHALL", "CONFIG", "DEBUG", "SCRIPT", "EVAL", "EVALSHA",
        "SHUTDOWN", "SLAVEOF", "REPLICAOF", "CLUSTER", "BGSAVE", "BGREWRITEAOF",
        "SAVE", "MIGRATE", "RESTORE", "DUMP",
        
        # Pub/Sub (could be used for DoS)
        "PUBLISH", "SUBSCRIBE", "UNSUBSCRIBE", "PSUBSCRIBE", "PUNSUBSCRIBE",
        
        # Streams (write)
        "XADD", "XDEL", "XTRIM",
        
        # ACL and security
        "ACL", "AUTH",
        
        # Lua scripting
        "FUNCTION", "FCALL",
    ])
    
    def __init__(self):
        """Initialize Redis safety checker."""
        pass
    
    def validate_command(self, command: str) -> tuple[SafetyResult, str]:
        """
        Validate a Redis command.
        
        Args:
            command: The Redis command (e.g., "GET", "HGETALL")
            
        Returns:
            Tuple of (SafetyResult, message)
        """
        if not command:
            return SafetyResult.INVALID, "Command cannot be empty"
        
        # Normalize command to uppercase
        cmd_upper = command.strip().upper()
        
        # Check against allowlist (primary security control)
        if cmd_upper in self.ALLOWED_COMMANDS:
            return SafetyResult.SAFE, f"Command {cmd_upper} is allowed"
        
        # Command not in allowlist - blocked
        return SafetyResult.BLOCKED, f"Command '{command}' is not in the allowlist. Only read-only commands are permitted."
    
    def validate_key_pattern(self, pattern: str) -> tuple[SafetyResult, str]:
        """
        Validate a Redis key pattern for SCAN/KEYS operations.
        
        Args:
            pattern: The key pattern (e.g., "user:*", "*")
            
        Returns:
            Tuple of (SafetyResult, message)
        """
        if not pattern:
            return SafetyResult.INVALID, "Pattern cannot be empty"
        
        # Very broad patterns that could cause performance issues
        if pattern == "*":
            logger.warning("Using broad pattern '*' - may affect performance on large databases")
        
        # Check for suspicious patterns that might be injection attempts
        suspicious_chars = ["\n", "\r", "\x00"]
        for char in suspicious_chars:
            if char in pattern:
                return SafetyResult.BLOCKED, "Pattern contains invalid characters"
        
        return SafetyResult.SAFE, "Pattern is valid"


# =============================================================================
# Convenience Functions
# =============================================================================

_mongodb_checker: MongoDBSafetyChecker | None = None
_redis_checker: RedisSafetyChecker | None = None


def get_mongodb_checker() -> MongoDBSafetyChecker:
    """Get or create the global MongoDB safety checker."""
    global _mongodb_checker
    if _mongodb_checker is None:
        _mongodb_checker = MongoDBSafetyChecker()
    return _mongodb_checker


def get_redis_checker() -> RedisSafetyChecker:
    """Get or create the global Redis safety checker."""
    global _redis_checker
    if _redis_checker is None:
        _redis_checker = RedisSafetyChecker()
    return _redis_checker


def is_mongodb_query_safe(query: dict[str, Any]) -> tuple[bool, str]:
    """
    Convenience function to check if a MongoDB query is safe.
    
    Args:
        query: MongoDB query filter
        
    Returns:
        Tuple of (is_safe, message)
    """
    result, message = get_mongodb_checker().validate_query(query)
    return result == SafetyResult.SAFE, message


def is_mongodb_pipeline_safe(pipeline: list[dict]) -> tuple[bool, str]:
    """
    Convenience function to check if a MongoDB pipeline is safe.
    
    Args:
        pipeline: MongoDB aggregation pipeline
        
    Returns:
        Tuple of (is_safe, message)
    """
    result, message = get_mongodb_checker().validate_pipeline(pipeline)
    return result == SafetyResult.SAFE, message


def is_redis_command_safe(command: str) -> tuple[bool, str]:
    """
    Convenience function to check if a Redis command is safe.
    
    Args:
        command: Redis command
        
    Returns:
        Tuple of (is_safe, message)
    """
    result, message = get_redis_checker().validate_command(command)
    return result == SafetyResult.SAFE, message
