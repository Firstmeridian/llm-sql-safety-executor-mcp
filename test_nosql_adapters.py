"""
NoSQL Adapter Tests

Tests for MongoDB and Redis adapters including:
- Safety checker validation
- Adapter functionality
- Error handling

Requirements:
- MongoDB running on localhost:27017
- Redis running on localhost:6379

Run with: pytest test_nosql_adapters.py -v
"""

import pytest
import os

# Set test environment variables before importing adapters
os.environ.setdefault("ENABLED_DATASOURCES", "mysql,mongodb,redis")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("REDIS_HOST", "localhost")


# =============================================================================
# MongoDB Safety Checker Tests
# =============================================================================

class TestMongoDBSafetyChecker:
    """Tests for MongoDB query and pipeline validation."""
    
    def setup_method(self):
        """Setup for each test."""
        from nosql_safety_checker import MongoDBSafetyChecker, SafetyResult
        self.checker = MongoDBSafetyChecker()
        self.SafetyResult = SafetyResult
    
    # --- Safe Query Tests ---
    
    def test_empty_query_is_safe(self):
        """Empty query should be safe."""
        result, msg = self.checker.validate_query({})
        assert result == self.SafetyResult.SAFE
    
    def test_simple_equality_query_is_safe(self):
        """Simple equality query should be safe."""
        result, msg = self.checker.validate_query({"name": "test"})
        assert result == self.SafetyResult.SAFE
    
    def test_comparison_operators_are_safe(self):
        """Standard comparison operators should be safe."""
        queries = [
            {"age": {"$gt": 18}},
            {"price": {"$lte": 100}},
            {"status": {"$in": ["active", "pending"]}},
            {"tags": {"$all": ["a", "b"]}},
        ]
        for query in queries:
            result, msg = self.checker.validate_query(query)
            assert result == self.SafetyResult.SAFE, f"Query {query} should be safe"
    
    def test_logical_operators_are_safe(self):
        """Logical operators should be safe."""
        query = {
            "$and": [
                {"status": "active"},
                {"age": {"$gte": 21}}
            ]
        }
        result, msg = self.checker.validate_query(query)
        assert result == self.SafetyResult.SAFE
    
    def test_nested_query_is_safe(self):
        """Nested document query should be safe."""
        query = {"user.profile.age": {"$gt": 18}}
        result, msg = self.checker.validate_query(query)
        assert result == self.SafetyResult.SAFE
    
    # --- Blocked Query Tests ---
    
    def test_where_operator_is_blocked(self):
        """$where operator should be blocked (JavaScript execution)."""
        query = {"$where": "this.a > this.b"}
        result, msg = self.checker.validate_query(query)
        assert result == self.SafetyResult.BLOCKED
        assert "$where" in msg
    
    def test_function_operator_is_blocked(self):
        """$function operator should be blocked."""
        query = {
            "$expr": {
                "$function": {
                    "body": "function(x) { return x * 2; }",
                    "args": ["$value"],
                    "lang": "js"
                }
            }
        }
        result, msg = self.checker.validate_query(query)
        assert result == self.SafetyResult.BLOCKED
    
    def test_nested_blocked_operator(self):
        """Blocked operator nested in query should be detected."""
        query = {
            "$and": [
                {"status": "active"},
                {"$where": "this.a > 0"}
            ]
        }
        result, msg = self.checker.validate_query(query)
        assert result == self.SafetyResult.BLOCKED
    
    # --- Pipeline Tests ---
    
    def test_empty_pipeline_is_safe(self):
        """Empty pipeline should be safe."""
        result, msg = self.checker.validate_pipeline([])
        assert result == self.SafetyResult.SAFE
    
    def test_match_stage_is_safe(self):
        """$match stage should be safe."""
        pipeline = [{"$match": {"status": "active"}}]
        result, msg = self.checker.validate_pipeline(pipeline)
        assert result == self.SafetyResult.SAFE
    
    def test_group_stage_is_safe(self):
        """$group stage should be safe."""
        pipeline = [
            {"$group": {"_id": "$category", "count": {"$sum": 1}}}
        ]
        result, msg = self.checker.validate_pipeline(pipeline)
        assert result == self.SafetyResult.SAFE
    
    def test_lookup_stage_is_safe(self):
        """$lookup stage should be safe."""
        pipeline = [
            {
                "$lookup": {
                    "from": "orders",
                    "localField": "_id",
                    "foreignField": "userId",
                    "as": "orders"
                }
            }
        ]
        result, msg = self.checker.validate_pipeline(pipeline)
        assert result == self.SafetyResult.SAFE
    
    def test_out_stage_is_blocked(self):
        """$out stage should be blocked (writes data)."""
        pipeline = [
            {"$match": {"status": "active"}},
            {"$out": "results_collection"}
        ]
        result, msg = self.checker.validate_pipeline(pipeline)
        assert result == self.SafetyResult.BLOCKED
        assert "$out" in msg.lower()
    
    def test_merge_stage_is_blocked(self):
        """$merge stage should be blocked (writes data)."""
        pipeline = [
            {"$match": {"status": "active"}},
            {"$merge": {"into": "results", "whenMatched": "replace"}}
        ]
        result, msg = self.checker.validate_pipeline(pipeline)
        assert result == self.SafetyResult.BLOCKED
        assert "$merge" in msg.lower()
    
    def test_accumulator_in_group_is_blocked(self):
        """$accumulator in $group should be blocked (JavaScript)."""
        pipeline = [
            {
                "$group": {
                    "_id": "$category",
                    "customSum": {
                        "$accumulator": {
                            "init": "function() { return 0; }",
                            "accumulate": "function(state, value) { return state + value; }",
                            "accumulateArgs": ["$value"],
                            "merge": "function(s1, s2) { return s1 + s2; }",
                            "finalize": "function(state) { return state; }",
                            "lang": "js"
                        }
                    }
                }
            }
        ]
        result, msg = self.checker.validate_pipeline(pipeline)
        assert result == self.SafetyResult.BLOCKED


# =============================================================================
# Redis Safety Checker Tests
# =============================================================================

class TestRedisSafetyChecker:
    """Tests for Redis command validation."""
    
    def setup_method(self):
        """Setup for each test."""
        from nosql_safety_checker import RedisSafetyChecker, SafetyResult
        self.checker = RedisSafetyChecker()
        self.SafetyResult = SafetyResult
    
    # --- Allowed Commands ---
    
    def test_get_is_allowed(self):
        """GET command should be allowed."""
        result, msg = self.checker.validate_command("GET")
        assert result == self.SafetyResult.SAFE
    
    def test_mget_is_allowed(self):
        """MGET command should be allowed."""
        result, msg = self.checker.validate_command("MGET")
        assert result == self.SafetyResult.SAFE
    
    def test_hgetall_is_allowed(self):
        """HGETALL command should be allowed."""
        result, msg = self.checker.validate_command("HGETALL")
        assert result == self.SafetyResult.SAFE
    
    def test_lrange_is_allowed(self):
        """LRANGE command should be allowed."""
        result, msg = self.checker.validate_command("LRANGE")
        assert result == self.SafetyResult.SAFE
    
    def test_smembers_is_allowed(self):
        """SMEMBERS command should be allowed."""
        result, msg = self.checker.validate_command("SMEMBERS")
        assert result == self.SafetyResult.SAFE
    
    def test_zrange_is_allowed(self):
        """ZRANGE command should be allowed."""
        result, msg = self.checker.validate_command("ZRANGE")
        assert result == self.SafetyResult.SAFE
    
    def test_scan_is_allowed(self):
        """SCAN command should be allowed."""
        result, msg = self.checker.validate_command("SCAN")
        assert result == self.SafetyResult.SAFE
    
    def test_type_is_allowed(self):
        """TYPE command should be allowed."""
        result, msg = self.checker.validate_command("TYPE")
        assert result == self.SafetyResult.SAFE
    
    def test_info_is_allowed(self):
        """INFO command should be allowed."""
        result, msg = self.checker.validate_command("INFO")
        assert result == self.SafetyResult.SAFE
    
    def test_case_insensitive(self):
        """Commands should be case-insensitive."""
        for cmd in ["get", "Get", "GET", "gEt"]:
            result, msg = self.checker.validate_command(cmd)
            assert result == self.SafetyResult.SAFE
    
    # --- Blocked Commands ---
    
    def test_set_is_blocked(self):
        """SET command should be blocked."""
        result, msg = self.checker.validate_command("SET")
        assert result == self.SafetyResult.BLOCKED
    
    def test_del_is_blocked(self):
        """DEL command should be blocked."""
        result, msg = self.checker.validate_command("DEL")
        assert result == self.SafetyResult.BLOCKED
    
    def test_flushall_is_blocked(self):
        """FLUSHALL command should be blocked."""
        result, msg = self.checker.validate_command("FLUSHALL")
        assert result == self.SafetyResult.BLOCKED
    
    def test_flushdb_is_blocked(self):
        """FLUSHDB command should be blocked."""
        result, msg = self.checker.validate_command("FLUSHDB")
        assert result == self.SafetyResult.BLOCKED
    
    def test_config_is_blocked(self):
        """CONFIG command should be blocked."""
        result, msg = self.checker.validate_command("CONFIG")
        assert result == self.SafetyResult.BLOCKED
    
    def test_eval_is_blocked(self):
        """EVAL command should be blocked (Lua scripting)."""
        result, msg = self.checker.validate_command("EVAL")
        assert result == self.SafetyResult.BLOCKED
    
    def test_script_is_blocked(self):
        """SCRIPT command should be blocked."""
        result, msg = self.checker.validate_command("SCRIPT")
        assert result == self.SafetyResult.BLOCKED
    
    def test_shutdown_is_blocked(self):
        """SHUTDOWN command should be blocked."""
        result, msg = self.checker.validate_command("SHUTDOWN")
        assert result == self.SafetyResult.BLOCKED
    
    # --- Pattern Validation ---
    
    def test_valid_pattern(self):
        """Normal key patterns should be valid."""
        patterns = ["user:*", "*:cache", "session:123", "*"]
        for pattern in patterns:
            result, msg = self.checker.validate_key_pattern(pattern)
            assert result == self.SafetyResult.SAFE
    
    def test_empty_pattern_is_invalid(self):
        """Empty pattern should be invalid."""
        result, msg = self.checker.validate_key_pattern("")
        assert result == self.SafetyResult.INVALID


# =============================================================================
# MongoDB Adapter Tests (Integration)
# =============================================================================

@pytest.mark.integration
class TestMongoDBAdapter:
    """Integration tests for MongoDB adapter."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        try:
            from mongodb_adapter import MongoDBAdapter
            self.adapter = MongoDBAdapter()
            connected = self.adapter.connect()
            if not connected:
                pytest.skip("MongoDB not available")
        except ImportError:
            pytest.skip("pymongo not installed")
        except Exception as e:
            pytest.skip(f"MongoDB connection failed: {e}")
    
    def test_check_connection(self):
        """Test connection check."""
        success, msg = self.adapter.check_connection()
        assert success is True
    
    def test_list_databases(self):
        """Test listing databases."""
        result = self.adapter.list_databases()
        assert isinstance(result, list)
        # Should not include system databases by default
        for db in result:
            assert db["name"] not in ["admin", "config", "local"]
    
    def test_list_collections(self):
        """Test listing collections in a database."""
        # First ensure we have a test database
        result = self.adapter.list_collections("test")
        assert isinstance(result, list)
    
    def test_find_empty_collection(self):
        """Test find on empty/non-existent collection."""
        result = self.adapter.find(
            database="test",
            collection="nonexistent_collection_xyz",
            filter={}
        )
        assert isinstance(result, list)
        assert len(result) == 0
    
    def test_count_documents(self):
        """Test counting documents."""
        result = self.adapter.count_documents(
            database="test",
            collection="nonexistent_collection_xyz",
            filter={}
        )
        assert result == 0 or isinstance(result, int)


# =============================================================================
# Redis Adapter Tests (Integration)
# =============================================================================

@pytest.mark.integration
class TestRedisAdapter:
    """Integration tests for Redis adapter."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test fixtures."""
        try:
            from redis_adapter import RedisAdapter
            self.adapter = RedisAdapter()
            connected = self.adapter.connect()
            if not connected:
                pytest.skip("Redis not available")
        except ImportError:
            pytest.skip("redis not installed")
        except Exception as e:
            pytest.skip(f"Redis connection failed: {e}")
    
    def test_check_connection(self):
        """Test connection check."""
        success, msg = self.adapter.check_connection()
        assert success is True
    
    def test_dbsize(self):
        """Test getting database size."""
        result = self.adapter.dbsize()
        assert isinstance(result, dict)
        assert "key_count" in result
        assert result["key_count"] >= 0
    
    def test_info(self):
        """Test getting server info."""
        result = self.adapter.info("server")
        assert isinstance(result, dict)
    
    def test_get_nonexistent_key(self):
        """Test getting non-existent key."""
        result = self.adapter.get("nonexistent_key_xyz_123")
        assert isinstance(result, dict)
        assert result["exists"] is False
    
    def test_scan_keys(self):
        """Test scanning keys."""
        result = self.adapter.scan("*", count=10)
        assert isinstance(result, dict)
        assert "keys" in result
        assert isinstance(result["keys"], list)
    
    def test_type_nonexistent(self):
        """Test type of non-existent key."""
        result = self.adapter.type("nonexistent_key_xyz_123")
        assert isinstance(result, dict)
        assert result["type"] == "none"


# =============================================================================
# Adapter Manager Tests
# =============================================================================

class TestAdapterManager:
    """Tests for adapter manager."""
    
    def test_get_enabled_datasources(self):
        """Test getting enabled datasources."""
        from adapter_manager import get_enabled_datasources
        datasources = get_enabled_datasources()
        assert isinstance(datasources, list)
    
    def test_is_datasource_enabled(self):
        """Test checking if datasource is enabled."""
        from adapter_manager import is_datasource_enabled
        # Check some common datasources
        result = is_datasource_enabled("mysql")
        assert isinstance(result, bool)
    
    def test_adapter_manager_singleton(self):
        """Test adapter manager singleton pattern."""
        from adapter_manager import get_adapter_manager, reset_adapter_manager
        
        manager1 = get_adapter_manager()
        manager2 = get_adapter_manager()
        assert manager1 is manager2
        
        reset_adapter_manager()
        manager3 = get_adapter_manager()
        assert manager1 is not manager3


# =============================================================================
# Convenience Function Tests
# =============================================================================

class TestConvenienceFunctions:
    """Tests for convenience functions in nosql_safety_checker."""
    
    def test_is_mongodb_query_safe(self):
        """Test MongoDB query safety convenience function."""
        from nosql_safety_checker import is_mongodb_query_safe
        
        # Safe query
        is_safe, msg = is_mongodb_query_safe({"name": "test"})
        assert is_safe is True
        
        # Unsafe query
        is_safe, msg = is_mongodb_query_safe({"$where": "this.a > 0"})
        assert is_safe is False
    
    def test_is_mongodb_pipeline_safe(self):
        """Test MongoDB pipeline safety convenience function."""
        from nosql_safety_checker import is_mongodb_pipeline_safe
        
        # Safe pipeline
        is_safe, msg = is_mongodb_pipeline_safe([{"$match": {"x": 1}}])
        assert is_safe is True
        
        # Unsafe pipeline
        is_safe, msg = is_mongodb_pipeline_safe([{"$out": "collection"}])
        assert is_safe is False
    
    def test_is_redis_command_safe(self):
        """Test Redis command safety convenience function."""
        from nosql_safety_checker import is_redis_command_safe
        
        # Safe command
        is_safe, msg = is_redis_command_safe("GET")
        assert is_safe is True
        
        # Unsafe command
        is_safe, msg = is_redis_command_safe("SET")
        assert is_safe is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
