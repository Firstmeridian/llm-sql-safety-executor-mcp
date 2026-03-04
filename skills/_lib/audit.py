"""
Audit Logger Module — JSONL Audit Trail for Mutation Operations

Records all mutation skill operations (preview and execute) to a JSONL file.
Each line is a self-contained JSON object with:
- who: Agent identity (ctx.client_id or AGENT_ID env var)
- what: skill_name + params + mode (preview/execute)
- when: ISO 8601 timestamp
- result: success/failure + rowcount

Concurrency Safety:
- stdio mode: Single client, no concurrency risk.
- SSE multi-client mode: Uses threading.Lock to prevent JSON line corruption.
  For high-throughput production, consider fcntl.flock() or database-backed audit.

Design References:
- DRAFTPLAN_final.md Step 7
- SAFETY.md #10: Audit logging for all mutation operations
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Thread lock for concurrent JSONL writes (SSE multi-client safety)
_write_lock = threading.Lock()


class AuditLogger:
    """
    Append-only JSONL audit logger for mutation operations.

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
    ) -> None:
        """
        Append an audit entry to the JSONL log file.

        Args:
            skill_name: Name of the mutation skill
            params: Parameters passed to the skill
            mode: "preview" or "execute"
            result: Result dict from the operation
            client_id: MCP client identity (from ctx.client_id if available)
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

        try:
            line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
            with _write_lock:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception as e:
            # Audit logging failure should not break the operation
            logger.error(f"Failed to write audit log: {e}")


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
