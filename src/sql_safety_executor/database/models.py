from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pydantic import SecretStr

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConnectionPolicy:
    """Read and mutation policy bound to one configured database connection."""

    allow_union: bool = False
    allowed_tables: frozenset[str] = frozenset()
    read_mode: str = "allowlist"
    allow_mutations: bool = False
    mutation_skills: frozenset[str] = frozenset()
    # MySQL table identity may be case-sensitive (lower_case_table_names=0).
    case_sensitive_tables: bool = False

    def table_key(self, name: str) -> str:
        return name if self.case_sensitive_tables else name.lower()

    def allows_table(self, name: str) -> bool:
        if "*" in self.allowed_tables:
            return True
        return self.table_key(name) in self.allowed_tables


@dataclass(frozen=True)
class DatabaseConfig:
    """Sanitized runtime configuration for one named database connection."""

    connection_id: str
    db_type: str
    query_timeout_seconds: int
    connect_timeout_seconds: int
    policy: ConnectionPolicy
    mysql_user: str | None = None
    mysql_password: SecretStr | None = field(default=None, repr=False)
    mysql_host: str | None = None
    mysql_database: str | None = None
    sqlite_database_path: str | None = None
    sqlite_progress_handler_interval: int = 100
