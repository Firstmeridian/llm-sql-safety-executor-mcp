from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pydantic import SecretStr
from .identifiers import ascii_identifier_lower
from .relations import RelationReference

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
    allowed_relations: frozenset[RelationReference] | None = None
    default_schema: str | None = None
    _relation_grants: frozenset[RelationReference] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_relation_grants", frozenset(
            self.relation_key(RelationReference.from_declaration(name).in_schema(self.default_schema))
            for name in self.allowed_tables or () if name != "*"
        ) if self.allowed_relations is None else frozenset(
            self.relation_key(reference.in_schema(self.default_schema)) for reference in self.allowed_relations
        ))

    def table_key(self, name: str) -> str:
        return name if self.case_sensitive_tables else ascii_identifier_lower(name)

    def allows_table(self, name: str) -> bool:
        """Check a configured/declarative name, not a decoded SQL token."""
        return self.allows_relation(RelationReference.from_declaration(name))

    def relation_key(self, relation: RelationReference) -> RelationReference:
        return relation.key(case_sensitive=self.case_sensitive_tables)

    def allows_relation(self, relation: RelationReference, *, default_schema: str | None = None) -> bool:
        """Bare declarations identify the bound default object, never a shadow."""
        schema = default_schema or self.default_schema
        resolved = self.relation_key(relation.in_schema(schema))
        if self.allowed_tables is None or "*" in self.allowed_tables:
            return schema is None or resolved.schema == self.table_key(schema)
        if schema == self.default_schema:
            return resolved in self._relation_grants
        return resolved in {
            self.relation_key(grant.in_schema(schema)) for grant in self._relation_grants
        }

    def allows_metadata_table(self, name: str, schema: str | None) -> bool:
        """Metadata is bound to a known schema; names here are already decoded."""
        return self.allows_metadata_relation(RelationReference(name, schema))

    def allows_metadata_relation(self, relation: RelationReference) -> bool:
        """A bare declaration can authorize metadata in its fixed schema."""
        return self.allows_relation(relation, default_schema=self.default_schema or relation.schema)

    def allows_resolved_relation(self, relation: RelationReference, default_schema: str) -> bool:
        """A bare grant applies to the default schema, never any same-name object."""
        return self.allows_relation(relation, default_schema=default_schema)


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
    mysql_sql_mode: tuple[str, ...] | None = None
    sqlite_database_path: str | None = None
    sqlite_progress_handler_interval: int = 100
