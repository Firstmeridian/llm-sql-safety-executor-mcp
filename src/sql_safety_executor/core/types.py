"""Protocol-independent application types and safe, intentional failures."""

from dataclasses import dataclass, field
from typing import Any, Protocol
from pydantic_core import to_json

from sql_safety_executor.database.base import DatabaseAdapter
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.relations import RelationReference, SQLiteJSONNameObservation


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

    @property
    def default_schema(self) -> str | None:
        return "main" if self.db_type == "sqlite" else self.config.mysql_database

    def metadata_relation(self, name: str) -> RelationReference:
        """Bind a decoded metadata-tool name once, before authorization/rendering."""
        return RelationReference(name, self.default_schema)


@dataclass(frozen=True)
class SkillSchemaSnapshot:
    enabled: bool
    available: bool
    table_names: frozenset[RelationReference]
    schema_name: str | None = None
    json_name_observation: SQLiteJSONNameObservation | None = None
