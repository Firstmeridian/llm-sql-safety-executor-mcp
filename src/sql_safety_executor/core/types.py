"""Protocol-independent application types and safe, intentional failures."""

from dataclasses import dataclass, field
from typing import Any, Protocol
from pydantic_core import to_json

from sql_safety_executor.database.base import DatabaseAdapter
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig


class OperationError(Exception):
    """An intentionally public, sanitized application rejection."""


class OperationContext(Protocol):
    async def info(self, message: str) -> None: ...
    async def warning(self, message: str) -> None: ...
    async def error(self, message: str) -> None: ...


class NullContext:
    async def info(self, message: str) -> None:
        pass

    async def warning(self, message: str) -> None:
        pass

    async def error(self, message: str) -> None:
        pass


@dataclass
class OperationResult:
    structured_content: dict[str, Any]
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Keep serialization failures inside the execution-outcome boundary.
        # Protocol encoding after returning from a committed write is too late.
        to_json(self.structured_content)
        to_json(self.meta)


@dataclass(frozen=True)
class ConnectionContext:
    connection_id: str
    config: DatabaseConfig
    adapter: DatabaseAdapter
    policy: ConnectionPolicy

    @property
    def db_type(self) -> str:
        return self.config.db_type


@dataclass(frozen=True)
class SkillSchemaSnapshot:
    enabled: bool
    available: bool
    table_names: frozenset[str]
