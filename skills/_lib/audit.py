"""
Audit Logger Module — JSONL Audit Trail for Skill Operations

Records mutation skill operations and optional query skill executions to a JSONL file.
Each line is a self-contained JSON object with:
- who: Agent identity (ctx.client_id or AGENT_ID env var)
- what: skill_name + params + mode (query/preview/execute)
- when: ISO 8601 timestamp
- result: success/failure + rowcount + transaction outcome/error code when known

Concurrency Safety:
- A process-local threading.Lock prevents concurrent calls in this process from
  interleaving JSONL writes, regardless of transport.
- The lock does not coordinate multiple processes. The supported mutation
  deployment uses one process; any future multi-process audit design needs an
  external file lock or centralized audit sink.

Design References:
- skills/SAFETY.md #10: Best-effort audit logging for mutation operations
- DESIGN_RISK_REGISTER.md DRR-2026-022: Audit completeness boundary
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Process-local lock for concurrent JSONL writes.
_write_lock = threading.Lock()


class AuditLogger:
    """
    Append-only JSONL audit logger for skill operations.

    Attributes:
        log_path: Path to the JSONL audit log file.
        agent_id: Default agent identifier (from env var AGENT_ID).
    """

    def __init__(self, log_path: Path | str | None = None):
        """
        Initialize the audit logger.

        Args:
            log_path: Path to the audit log file.
                      Defaults to SKILLS_AUDIT_LOG env var or skills/_audit.jsonl.
        """
        if log_path is None:
            log_path = os.getenv("SKILLS_AUDIT_LOG", "skills/_audit.jsonl")
        self.log_path = Path(log_path)
        self.agent_id = os.getenv("AGENT_ID", "unknown")

        # Ensure parent directory exists
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning(
                f"Cannot create audit log directory '{self.log_path.parent}': {e}. "
                "Audit logging may fail at write time."
            )

    def log(
        self,
        skill_name: str,
        params: dict,
        mode: str,
        result: dict,
        client_id: str | None = None,
        connection_id: str | None = None,
        db_type: str | None = None,
    ) -> bool:
        """
        Append an audit entry to the JSONL log file.

        Args:
            skill_name: Name of the skill
            params: Parameters passed to the skill
            mode: "query", "preview", or "execute"
            result: Result dict from the operation
            client_id: MCP client identity (from ctx.client_id if available)
            connection_id: Optional configured connection id. This is a safe
                alias, not a DSN or credential.
            db_type: Optional actual database type for the selected connection.

        Returns:
            True when the audit entry was written, False when logging failed.
            Logging failures are best-effort and do not raise.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": client_id or self.agent_id,
            "skill_name": skill_name,
            "mode": mode,
            "params": _sanitize_params(params),
            "success": result.get("success", False),
            "rowcount": result.get("rowcount"),
            "error": result.get("error"),
        }
        if connection_id is not None:
            entry["connection_id"] = connection_id
        if db_type is not None:
            entry["db_type"] = db_type
        if "total_rows" in result:
            entry["total_rows"] = result.get("total_rows")
        if "truncated" in result:
            entry["truncated"] = result.get("truncated")
        if "execution_outcome" in result:
            entry["execution_outcome"] = result.get("execution_outcome")
        if "error_code" in result:
            entry["error_code"] = result.get("error_code")

        try:
            line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
            with _write_lock:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(line)
            return True
        except Exception as e:
            # Audit logging failure should not break the operation
            logger.error(f"Failed to write audit log: {e}")
            return False


def _sanitize_params(params: dict) -> dict:
    """
    Sanitize parameters for audit logging.

    Truncates overly long string values to prevent log bloat.
    Does not redact — audit logs are internal, not client-facing.

    Args:
        params: Raw parameter dict

    Returns:
        Sanitized copy of the dict
    """
    sanitized = {}
    for k, v in params.items():
        if isinstance(v, str) and len(v) > 500:
            sanitized[k] = v[:497] + "..."
        else:
            sanitized[k] = v
    return sanitized
