from typing import Literal
from pydantic import Field

SchemaDetailLevel = Literal["compact", "full"]
SkillListDetailLevel = Literal["compact", "summary", "full"]
SkillDetailProjection = Literal["execution", "full"]
_SQL_QUERY_FIELD = Field(
    min_length=1,
    description="Read-only SQL query (SELECT, DESCRIBE or non-ANALYZE EXPLAIN).",
)
_SCHEMA_DETAIL_LEVELS: tuple[SchemaDetailLevel, ...] = ("compact", "full")

MUTATION_PREVIEW_BINDING_MAX_BYTES = 4096

_SKILLS_DETAIL_LEVELS: tuple[SkillListDetailLevel, ...] = (
    "compact",
    "summary",
    "full",
)

SKILLS_SEARCH_MAX_LENGTH = 128

SKILLS_CATEGORY_MAX_LENGTH = 64

_EXPLAIN_UPDATE_MODIFIERS = {"LOW_PRIORITY", "IGNORE"}

_EXPLAIN_INSERT_MODIFIERS = {
    "LOW_PRIORITY",
    "DELAYED",
    "HIGH_PRIORITY",
    "IGNORE",
}

_EXPLAIN_REPLACE_MODIFIERS = {"LOW_PRIORITY", "DELAYED"}

_EXPLAIN_DELETE_MODIFIERS = {"LOW_PRIORITY", "QUICK", "IGNORE"}

MYSQL_FILE_OPERATION_PATTERNS = [
    r"\bINTO\s+(?:OUTFILE|DUMPFILE)\b",
    r"\bLOAD_FILE\s*\(",
]

_CONNECTION_ID_FIELD = Field(
    description=(
        "Connection alias. Pass exact aliases unchanged; omit only for default. "
        "Pass a resolved user/application target or unique db_type match explicitly. "
        "Use list_connections() to discover aliases or match a database type. "
        "For an unresolved purpose, ambiguous reference or irreconcilable scope restrictions, list "
        "candidates if needed, then ask and wait before database work. "
        "A default flag or successful check is not target selection. "
        "Omission never means all connections."
    ),
    min_length=1,
    max_length=64,
)

_MUTATION_PREVIEW_TOKEN_FIELD = Field(
    description=(
        "API-opaque one-time bearer handle returned by "
        "execute_mutation_skill(confirm=false). Required when confirm=true; "
        "do not parse it or depend on its internal format."
    ),
    min_length=1,
    max_length=128,
)


_SKILL_DETAIL_PROJECTION_LEVELS = frozenset({"execution", "full"})
