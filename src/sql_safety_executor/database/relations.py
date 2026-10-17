"""Relation identity; display text never decides schema or object boundaries."""

from dataclasses import dataclass
from typing import Literal
from .identifiers import ascii_identifier_lower


@dataclass(frozen=True)
class RelationReference:
    name: str
    schema: str | None = None

    @classmethod
    def from_declaration(cls, value: str) -> "RelationReference":
        """Configured/declarative dots separate schema from name, once.

        These are name declarations, not SQL: quotation marks remain name data.
        SQL references are constructed from lexical components instead.
        """
        schema, separator, name = value.partition(".")
        return cls(name, schema) if separator else cls(value)

    def key(self, *, case_sensitive: bool) -> "RelationReference":
        if case_sensitive:
            return self
        return RelationReference(
            ascii_identifier_lower(self.name),
            ascii_identifier_lower(self.schema) if self.schema is not None else None,
        )

    @property
    def display_name(self) -> str:
        def display(value: str) -> str:
            return '"' + value.replace('"', '""') + '"' if "." in value or value == "*" else value
        name = display(self.name)
        return name if self.schema is None else f"{display(self.schema)}.{name}"

    def in_schema(self, schema: str | None) -> "RelationReference":
        return self if self.schema is not None else RelationReference(self.name, schema)


@dataclass(frozen=True)
class ReadRelation:
    """A table or view observed in one adapter's fixed metadata schema."""

    reference: RelationReference
    kind: Literal["table", "view"]


def render_relation(reference: RelationReference, db_type: str) -> str:
    """Quote components separately for generated database SQL.

    Metadata table-name validation belongs to the caller; configured schema
    names may contain characters outside that conservative table-name grammar.
    The transport layer protects literal colons from text()'s bind parser.
    This renderer only handles SQL identifiers, never parameter syntax.
    """
    if db_type not in ("sqlite", "mysql"):
        raise ValueError("Unsupported relation quoting dialect")
    delimiter = "`" if db_type == "mysql" else '"'

    def quote(value: str) -> str:
        if not value or "\x00" in value:
            raise ValueError("Invalid relation component")
        return delimiter + value.replace(delimiter, delimiter * 2) + delimiter

    name = quote(reference.name)
    return name if reference.schema is None else f"{quote(reference.schema)}.{name}"
