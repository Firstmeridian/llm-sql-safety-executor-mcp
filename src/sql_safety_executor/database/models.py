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
