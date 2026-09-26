"""
Tests for audit.py — JSONL Audit Trail Logging

Covers:
- Audit log recording (#13)
- Log file format (JSONL with expected fields)
- Parameter sanitization
- Thread safety (basic)
- Missing log directory creation

Usage:
    pytest tests/test_audit.py -v
"""

from tests.support import SCENARIO

import json
import logging

# Add project root and _lib to path


# =============================================================================
# test_audit_log_recorded (#13)
# =============================================================================

class TestAuditLogger:
    """Tests for AuditLogger class."""

    def test_audit_log_recorded(self, tmp_path):
        """#13: Mutation operation records expected fields to JSONL."""
        from sql_safety_executor.observability.audit import AuditLogger

        log_path = tmp_path / "audit.jsonl"
        logger = AuditLogger(log_path=log_path)

        result = logger.log(
            skill_name="sample-update-order-status",
            params={"order_id": 42, "new_status": "shipped"},
            mode="execute",
            result={
                "success": True,
                "rowcount": 1,
                "execution_outcome": "committed",
            },
            client_id="test-agent-001",
        )

        assert result is True
        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)

        assert entry["skill_name"] == "sample-update-order-status"
        assert entry["mode"] == "execute"
        assert entry["success"] is True
        assert entry["rowcount"] == 1
        assert entry["execution_outcome"] == "committed"
        assert entry["agent_id"] == "test-agent-001"
        assert entry["params"]["order_id"] == 42
        assert entry["params"]["new_status"] == "shipped"
        assert "timestamp" in entry

    def test_audit_log_preview_mode(self, tmp_path):
        """Preview mode is recorded with mode='preview'."""
        from sql_safety_executor.observability.audit import AuditLogger

        log_path = tmp_path / "audit.jsonl"
        logger = AuditLogger(log_path=log_path)

        logger.log(
            skill_name="test-skill",
            params={"id": 1},
            mode="preview",
            result={"success": True, "preview": True},
        )

        content = log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)
        assert entry["mode"] == "preview"

    def test_audit_log_records_optional_connection_metadata(self, tmp_path):
        """v3.5: audit can include safe connection alias and actual DB type."""
        from sql_safety_executor.observability.audit import AuditLogger

        log_path = tmp_path / "audit.jsonl"
        logger = AuditLogger(log_path=log_path)

        logger.log(
            skill_name="sample-monthly-sales-report-sqlite",
            params={"year": 2026, "month": 1},
            mode="query",
            result={"success": True, "rowcount": 1},
            connection_id="analytics",
            db_type="sqlite",
        )

        entry = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert entry["connection_id"] == "analytics"
        assert entry["db_type"] == "sqlite"

    def test_audit_log_multiple_entries(self, tmp_path):
        """Multiple log entries produce valid JSONL (one per line)."""
        from sql_safety_executor.observability.audit import AuditLogger

        log_path = tmp_path / "audit.jsonl"
        logger = AuditLogger(log_path=log_path)

        for i in range(3):
            logger.log(
                skill_name=f"skill-{i}",
                params={"id": i},
                mode="execute",
                result={"success": True, "rowcount": 1},
            )

        lines = log_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

        for i, line in enumerate(lines):
            entry = json.loads(line)
            assert entry["skill_name"] == f"skill-{i}"

    def test_audit_log_failure(self, tmp_path):
        """Failed operations are logged with error field."""
        from sql_safety_executor.observability.audit import AuditLogger

        log_path = tmp_path / "audit.jsonl"
        logger = AuditLogger(log_path=log_path)

        logger.log(
            skill_name="failing-skill",
            params={"id": 1},
            mode="execute",
            result={
                "success": False,
                "error": "Error: table not found",
                "execution_outcome": "rolled_back",
                "error_code": "database_execution_failed",
            },
        )

        content = log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)
        assert entry["success"] is False
        assert "table not found" in entry["error"]
        assert entry["execution_outcome"] == "rolled_back"
        assert entry["error_code"] == "database_execution_failed"

    def test_audit_log_creates_directory(self, tmp_path):
        """AuditLogger creates parent directory if it doesn't exist."""
        from sql_safety_executor.observability.audit import AuditLogger

        log_path = tmp_path / "subdir" / "nested" / "audit.jsonl"
        logger = AuditLogger(log_path=log_path)

        logger.log(
            skill_name="test",
            params={},
            mode="execute",
            result={"success": True},
        )

        assert log_path.exists()

    def test_audit_fallback_agent_id(self, tmp_path):
        """Without client_id, uses the configured agent_id or 'unknown'."""
        from sql_safety_executor.observability.audit import AuditLogger
        from unittest.mock import patch

        log_path = tmp_path / "audit.jsonl"

        with patch.dict(SCENARIO, {"AGENT_ID": "test-env-agent"}, clear=False):
            logger = AuditLogger(log_path=log_path, agent_id="test-env-agent")
            logger.log(
                skill_name="test",
                params={},
                mode="execute",
                result={"success": True},
            )

        content = log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)
        assert entry["agent_id"] == "test-env-agent"

    def test_audit_param_sanitization(self, tmp_path):
        """Long string parameters are truncated in the log."""
        from sql_safety_executor.observability.audit import AuditLogger

        log_path = tmp_path / "audit.jsonl"
        logger = AuditLogger(log_path=log_path)

        long_value = "x" * 600
        logger.log(
            skill_name="test",
            params={"data": long_value},
            mode="execute",
            result={"success": True},
        )

        content = log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)
        assert len(entry["params"]["data"]) == 500
        assert entry["params"]["data"].endswith("...")

    def test_audit_mkdir_permission_error_warns(self, tmp_path):
        """P3#6: mkdir failure logs warning but doesn't crash."""
        from sql_safety_executor.observability.audit import AuditLogger
        from unittest.mock import patch

        bad_path = tmp_path / "no-perms" / "audit.jsonl"

        with patch("pathlib.Path.mkdir", side_effect=PermissionError("denied")):
            # Should not raise — just log a warning
            audit_logger = AuditLogger(log_path=bad_path)
            assert audit_logger.log_path == bad_path

    def test_audit_write_failure_is_best_effort(self, tmp_path, caplog):
        """Write failure returns False and does not raise."""
        from sql_safety_executor.observability.audit import AuditLogger
        from unittest.mock import patch

        log_path = tmp_path / "audit.jsonl"
        logger = AuditLogger(log_path=log_path)

        with patch("builtins.open", side_effect=OSError("disk full")):
            with caplog.at_level(logging.ERROR):
                result = logger.log(
                    skill_name="test",
                    params={},
                    mode="execute",
                    result={"success": True},
                )

        assert result is False
        assert "Failed to write audit log" in caplog.text
