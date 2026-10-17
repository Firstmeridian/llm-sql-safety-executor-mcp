"""Immutable SQL interpretation context, independent of grants and execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .identifiers import ascii_identifier_lower

NameRole = Literal["schema", "relation", "column", "cte", "table_alias", "column_alias", "index"]


@dataclass(frozen=True)
class DialectContext:
    dialect: Literal["sqlite", "mysql"]
    sql_modes: frozenset[str] = frozenset()
    cte_case_sensitive: bool = False
    default_schema: str | None = None

    @property
    def fingerprint(self) -> tuple:
        return (self.dialect, tuple(sorted(self.sql_modes)), self.cte_case_sensitive, self.default_schema)

    def cte_key(self, name: str) -> str:
        return name if self.cte_case_sensitive else ascii_identifier_lower(name)

    def valid_name(self, name: str, role: NameRole) -> bool:
        # This is the supported name envelope, not a server syntax validator.
        if not isinstance(name, str) or not name or "\x00" in name:
            return False
        if self.dialect == "mysql":
            if any(ord(char) > 0xFFFF for char in name):
                return False
            if role in {"schema", "relation", "column"}:
                return len(name) <= 64 and not name.endswith(" ")
        return True


def mysql_modes(value: str | tuple[str, ...] | None) -> frozenset[str]:
    """Canonicalize mode vocabulary only; never apply this to business names."""
    values = value.split(",") if isinstance(value, str) else value or ()
    return frozenset(item.strip().upper() for item in values if item.strip())
