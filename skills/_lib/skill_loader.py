"""
Skill Loader Module — Discovery, Loading, and Validation for SQL Skills

Provides the core infrastructure for the Skills extension layer:
- discover(): Scans skills/ directory, parses skill_def.md YAML frontmatter,
  validates query SQL safety at startup (defense-in-depth), caches
  SQL templates, and pre-loads mutation module classes to eliminate
  TOCTOU risks and runtime disk I/O.
- load_query() / load_mutation(): Runtime loaders that return cached data.
- validate_name() / validate_params(): Input validation functions.
- generate_skills_md(): Generates a static SKILLS.md overview file.

Explicit Source Declaration:
  Each skill_def.md must include a mandatory 'source' field that explicitly
  declares the execution file (e.g. source: query.sql, source: mutation.py).
  This follows the Explicit Configuration principle — the same approach used
  by GitHub Actions (action.yml 'main'), npm (package.json 'main'), and
  Python (pyproject.toml entry points). The source filename is validated for:
  - Path traversal prevention (no / or \\, no leading .)
  - Suffix enforcement (query → .sql, mutation → .py)
  - Safe character set (^[a-zA-Z0-9][a-zA-Z0-9._-]*$)

Design References:
- Anthropic Agent Skills spec: skill_def.md format with YAML frontmatter
- Anthropic best practices: Progressive disclosure, error accountability
- MCP Spec §7: Validate all tool inputs, implement proper access controls
- Google Gemini: Strong schema principle, structured parameters

Security:
- Skill names validated via ^[a-z0-9][a-z0-9-]*$ regex (path traversal prevention)
- Frontmatter skill names must match their directory names (identity integrity)
- Source filenames validated via _validate_source_filename() (traversal, suffix, charset)
- Resolved path containment: symlinks cannot escape skill directory (_is_path_within)
- Query SQL templates pre-validated with is_sql_safe() at startup (fail-fast)
- Mutation source modules must export a concrete MutationBase subclass
- SQL and mutation classes cached in memory — runtime never touches disk
- validate_params() rejects extra parameters not defined in schema
- validate_params() fails closed on unsupported schema types
- SKILLS_DIR path constrained to project root (prevents .env poisoning)
"""

from __future__ import annotations

import re
import logging
import importlib.util
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from mutation_base import MutationBase

from sql_safety_checker import is_sql_safe

logger = logging.getLogger(__name__)

# Regex for valid skill names: lowercase alphanumeric + hyphens, must start with alnum
# Aligned with Anthropic Agent Skills spec name constraints
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SKILL_NAME_MAX_LENGTH = 64  # Consistent with _is_valid_identifier() limit

# Regex for valid source filenames: alnum start, allows alnum + dot + hyphen + underscore
# No path separators, no leading dot (prevents traversal and hidden files)
_SOURCE_FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
_SOURCE_FILENAME_MAX_LENGTH = 128

# Enforced suffix mapping: skill type -> required file extension
# query skills must use .sql files; mutation skills must use .py files
_SOURCE_SUFFIX_MAP: dict[str, str] = {
    "query": ".sql",
    "mutation": ".py",
}
_SUPPORTED_PARAM_TYPES = {"int", "float", "str", "bool"}
_JSON_BOOL_STRING_MAP = {"true": True, "false": False}


def _is_path_within(target: Path, parent: Path) -> bool:
    """Check that resolved target path is inside resolved parent directory."""
    try:
        target.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SkillMetadata:
    """
    Metadata for a single skill, parsed from skill_def.md YAML frontmatter.

    Fields marked with underscore prefix are internal (populated by discover(),
    not sourced from YAML frontmatter).
    """
    name: str
    type: Literal["query", "mutation"]
    source: str  # Explicit execution file reference (e.g. "query.sql", "mutation.py")
    risk: Literal["low", "medium", "high"]
    description: str
    params: dict[str, dict] = field(default_factory=dict)
    triggers: list[str] = field(default_factory=list)
    version: str = "1.0"
    enabled: bool = True
    idempotent: bool = False
    requires_confirmation: bool = False
    category: str | None = None
    related_skills: list[str] = field(default_factory=list)
    databases: list[str] | None = None  # Optional: supported DB types (e.g. ["mysql", "sqlite"]). None = all.
    profiles: list[str] = field(default_factory=list)  # Optional operational profile tags (e.g. ["demo"]).
    tables: list[str] = field(default_factory=list)
    # -- Internal fields (populated by discover(), not from YAML) --
    _sql_template: str | None = field(default=None, repr=False)
    _mutation_class: type | None = field(default=None, repr=False)


# =============================================================================
# Module-level cache (populated by discover())
# =============================================================================

_skills_cache: dict[str, SkillMetadata] = {}
_skills_dir: Path | None = None

QueryValidator = Callable[[str], tuple[bool, str | None]]


def _default_query_validator(sql: str) -> tuple[bool, str | None]:
    """Fallback query validator for direct skill_loader use outside MCP."""
    if is_sql_safe(sql):
        return True, None
    return False, "only SELECT/SHOW/DESCRIBE/EXPLAIN allowed"


# =============================================================================
# Public API — Startup
# =============================================================================

def discover(
    skills_dir: Path,
    query_validator: QueryValidator | None = None,
) -> dict[str, SkillMetadata]:
    """
    Scan skills/ directory, parse all skill_def.md frontmatter, and return
    metadata for enabled skills.

    Each skill_def.md must declare a 'source' field pointing to the execution
    file (e.g. source: query.sql). The source filename is validated for
    security (no path traversal, suffix must match type).

    For type: query skills, reads the source SQL file and runs query_validator
    at startup (defense-in-depth). MCP passes the same policy used by query(sql);
    direct skill_loader callers fall back to is_sql_safe(). Unsafe SQL causes
    the skill to be skipped with an error log.

    Validated SQL templates are cached in SkillMetadata._sql_template.
    Table names are extracted and stored in SkillMetadata.tables.

    Args:
        skills_dir: Path to the skills/ directory
        query_validator: Optional SQL safety policy callback.

    Returns:
        Dict mapping skill_name -> SkillMetadata for enabled skills
    """
    global _skills_cache, _skills_dir
    _skills_dir = skills_dir
    discovered: dict[str, SkillMetadata] = {}
    validate_query = query_validator or _default_query_validator

    if not skills_dir.is_dir():
        logger.warning(f"Skills directory not found: {skills_dir}")
        _skills_cache = discovered
        return discovered

    for entry in sorted(skills_dir.iterdir()):
        # Skip non-directories and internal dirs (e.g., _lib)
        if not entry.is_dir() or entry.name.startswith("_"):
            continue

        skill_md_path = entry / "skill_def.md"
        if not skill_md_path.is_file():
            continue

        try:
            metadata = _parse_skill_md(skill_md_path, entry.name)
        except Exception as e:
            logger.error(f"Failed to parse {skill_md_path}: {e}")
            continue

        # Skip disabled skills
        if not metadata.enabled:
            logger.info(f"Skill '{metadata.name}' is disabled, skipping")
            continue

        # For query skills: read and validate source SQL file at startup
        if metadata.type == "query":
            query_sql_path = entry / metadata.source
            if not query_sql_path.is_file():
                logger.error(
                    f"Skill '{metadata.name}': source file '{metadata.source}' not found"
                )
                continue

            # Symlink escape prevention: resolved path must stay within skill dir
            if not _is_path_within(query_sql_path, entry):
                logger.error(
                    f"Skill '{metadata.name}': source file '{metadata.source}' "
                    "resolves outside skill directory (symlink escape blocked)"
                )
                continue

            sql_template = query_sql_path.read_text(encoding="utf-8").strip()
            if not sql_template:
                logger.error(
                    f"Skill '{metadata.name}': source file '{metadata.source}' is empty"
                )
                continue

            # Defense-in-depth: validate SQL safety at startup (fail-fast)
            is_valid_sql, validation_error = validate_query(sql_template)
            if not is_valid_sql:
                logger.error(
                    f"Skill '{metadata.name}': '{metadata.source}' failed SQL safety policy, "
                    f"skipping ({validation_error})"
                )
                continue

            # Cache the SQL template (TOCTOU mitigation)
            metadata._sql_template = sql_template
            # Extract table names for SKILLS.md, availability checks, and code review.
            metadata.tables = _merge_unique(
                metadata.tables,
                _extract_table_names(sql_template),
            )

        elif metadata.type == "mutation":
            mutation_py_path = entry / metadata.source
            if not mutation_py_path.is_file():
                logger.error(
                    f"Skill '{metadata.name}': source file '{metadata.source}' not found"
                )
                continue

            # Symlink escape prevention: resolved path must stay within skill dir
            if not _is_path_within(mutation_py_path, entry):
                logger.error(
                    f"Skill '{metadata.name}': source file '{metadata.source}' "
                    "resolves outside skill directory (symlink escape blocked)"
                )
                continue

            # Pre-load mutation module class at startup (TOCTOU + performance)
            try:
                mutation_class = _load_mutation_class(
                    metadata.name, mutation_py_path
                )
                metadata._mutation_class = mutation_class
            except Exception as e:
                logger.error(
                    f"Skill '{metadata.name}': failed to load '{metadata.source}': {e}"
                )
                continue

        discovered[metadata.name] = metadata

    # Validate related_skills references (warning-only)
    for name, meta in discovered.items():
        for ref in meta.related_skills:
            if ref not in discovered:
                logger.warning(
                    f"Skill '{name}': related_skills references '{ref}' "
                    "which does not exist or is disabled"
                )

    _skills_cache = discovered
    logger.info(
        f"Discovered {len(discovered)} enabled skill(s): "
        f"{', '.join(sorted(discovered.keys()))}"
    )
    return discovered


def generate_skills_md(skills: dict[str, SkillMetadata], output_path: Path) -> None:
    """
    Generate a static skills/SKILLS.md overview file for human review.

    Lists all enabled skills with name, type, source, risk, description, and tables.
    Disabled skills are excluded.

    Args:
        skills: Dict of skill_name -> SkillMetadata (from discover())
        output_path: Path to write SKILLS.md
    """
    lines = [
        "# Skills Overview",
        "",
        "> Auto-generated by skill_loader.py — do not edit manually.",
        "",
        "| Name | Type | Source | Risk | Databases | Profiles | Tables | Description |",
        "|------|------|--------|------|-----------|----------|--------|-------------|",
    ]

    for name in sorted(skills.keys()):
        meta = skills[name]
        tables_str = ", ".join(meta.tables) if meta.tables else "—"
        databases_str = ", ".join(meta.databases) if meta.databases else "all"
        profiles_str = ", ".join(meta.profiles) if meta.profiles else "—"
        desc = meta.description.replace("\n", " ").strip()
        if len(desc) > 100:
            desc = desc[:97] + "..."
        lines.append(
            f"| {name} | {meta.type} | {meta.source} | {meta.risk} | {databases_str} | {profiles_str} | {tables_str} | {desc} |"
        )

    lines.append("")
    lines.append(f"Total: {len(skills)} skill(s)")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Generated {output_path} with {len(skills)} skill(s)")


# =============================================================================
# Public API — Runtime
# =============================================================================

def validate_name(skill_name: str) -> None:
    """
    Validate skill_name format. Must match ^[a-z0-9][a-z0-9-]*$ and be
    at most 64 characters. Prevents path traversal attacks.

    Must be called before any file I/O operations.

    Args:
        skill_name: The skill name to validate

    Raises:
        ValueError: If name is invalid
    """
    if not skill_name or len(skill_name) > _SKILL_NAME_MAX_LENGTH:
        raise ValueError(
            f"Invalid skill name: must be 1-{_SKILL_NAME_MAX_LENGTH} characters"
        )
    if not _SKILL_NAME_PATTERN.match(skill_name):
        raise ValueError(
            f"Invalid skill name '{skill_name}': must match pattern "
            f"^[a-z0-9][a-z0-9-]*$ (lowercase alphanumeric and hyphens only)"
        )


def _validate_skill_identity(raw_name: Any, dir_name: str, path: Path) -> str:
    """Validate that frontmatter name is a valid skill name matching the directory."""
    try:
        validate_name(dir_name)
    except ValueError as e:
        raise ValueError(
            f"Invalid skill directory name '{dir_name}' for {path}: {e}"
        ) from e

    if not isinstance(raw_name, str):
        raise ValueError(f"Invalid field 'name' in {path}: must be a string")

    try:
        validate_name(raw_name)
    except ValueError as e:
        raise ValueError(
            f"Invalid frontmatter field 'name' in {path}: {e}"
        ) from e

    if raw_name != dir_name:
        raise ValueError(
            f"Skill name mismatch in {path}: frontmatter name '{raw_name}' "
            f"must match directory name '{dir_name}'"
        )

    return raw_name


def load_query(skill_name: str) -> tuple[str, dict]:
    """
    Return (sql_template, param_schema) for a query skill.

    SQL template is read from the in-memory cache populated by discover(),
    NOT from disk — eliminates TOCTOU risk (post-startup file tampering
    does not affect runtime).

    Args:
        skill_name: Name of the query skill

    Returns:
        Tuple of (sql_template_string, params_schema_dict)

    Raises:
        FileNotFoundError: If skill not found in cache
        TypeError: If skill type is not 'query'
    """
    if skill_name not in _skills_cache:
        raise FileNotFoundError(f"Skill '{skill_name}' not found")

    metadata = _skills_cache[skill_name]
    if metadata.type != "query":
        raise TypeError(
            f"Skill '{skill_name}' is type '{metadata.type}', "
            "expected 'query'. Use execute_mutation_skill instead."
        )

    if metadata._sql_template is None:
        raise FileNotFoundError(
            f"Skill '{skill_name}': SQL template not cached (internal error)"
        )

    return metadata._sql_template, metadata.params


def load_mutation(skill_name: str, adapter, audit_logger) -> "MutationBase":
    """
    Instantiate a cached Mutation class with the given adapter and logger.

    The Mutation class is pre-loaded and cached by discover() at startup.
    This method only performs instantiation — no disk I/O or module compilation.

    Args:
        skill_name: Name of the mutation skill
        adapter: DatabaseAdapter instance for write operations
        audit_logger: AuditLogger instance for operation logging

    Returns:
        Instantiated MutationBase subclass

    Raises:
        FileNotFoundError: If skill not found in cache
        TypeError: If skill type is not 'mutation'
        RuntimeError: If mutation class was not cached (discover() issue)
    """
    if skill_name not in _skills_cache:
        raise FileNotFoundError(f"Skill '{skill_name}' not found")

    metadata = _skills_cache[skill_name]
    if metadata.type != "mutation":
        raise TypeError(
            f"Skill '{skill_name}' is type '{metadata.type}', "
            "expected 'mutation'. Use execute_query_skill instead."
        )

    if metadata._mutation_class is None:
        raise RuntimeError(
            f"Skill '{skill_name}': mutation class not cached "
            "(discover() may have failed to load source module)"
        )

    return metadata._mutation_class(adapter, audit_logger)


def validate_params(params: dict, schema: dict) -> dict:
    """
    Validate parameters against the frontmatter schema definition.

    Checks:
    - Required fields are present
    - Type coercion/validation (int, float, str, bool)
    - Range constraints (min, max)
    - Enum constraints

    Args:
        params: User-provided parameters
        schema: Schema dict from skill_def.md frontmatter params section

    Returns:
        Validated (and possibly coerced) parameters

    Raises:
        TypeError: If a parameter has wrong type
        ValueError: If a parameter is missing, out of range, or not in enum
    """
    validated = {}

    # Defense-in-depth: reject parameters not defined in schema
    unexpected = set(params.keys()) - set(schema.keys())
    if unexpected:
        raise ValueError(
            f"Unexpected parameter(s): {sorted(unexpected)}. "
            f"Allowed: {sorted(schema.keys())}"
        )

    for param_name, constraints in schema.items():
        required = constraints.get("required", False)

        if param_name not in params:
            if required:
                raise ValueError(
                    f"Missing required parameter: '{param_name}'"
                )
            continue  # Optional param not provided, skip

        value = params[param_name]

        # Type validation/coercion
        expected_type = constraints.get("type", "str")
        value = _coerce_type(param_name, value, expected_type)

        # Range validation
        if "min" in constraints and value < constraints["min"]:
            raise ValueError(
                f"Parameter '{param_name}' value {value} is below "
                f"minimum {constraints['min']}"
            )
        if "max" in constraints and value > constraints["max"]:
            raise ValueError(
                f"Parameter '{param_name}' value {value} exceeds "
                f"maximum {constraints['max']}"
            )

        # Enum validation
        if "enum" in constraints and value not in constraints["enum"]:
            raise ValueError(
                f"Parameter '{param_name}' value '{value}' is not one of: "
                f"{constraints['enum']}"
            )

        validated[param_name] = value

    return validated


def get_skills_cache() -> dict[str, SkillMetadata]:
    """Return the current skills cache (read-only access for MCP tools)."""
    return _skills_cache


# =============================================================================
# Internal Helpers
# =============================================================================

def _validate_source_filename(source: str, skill_type: str, path: Path) -> None:
    """
    Validate the 'source' field from skill_def.md YAML frontmatter.

    Security checks:
    - Must not contain path separators (/ or \\) — prevents directory traversal
    - Must not start with '.' — prevents hidden files and '..' traversal
    - Must match safe filename regex: ^[a-zA-Z0-9][a-zA-Z0-9._-]*$
    - Must not exceed 128 characters
    - Must have the correct suffix for the skill type (.sql for query, .py for mutation)

    Design decision: Explicit source declaration follows industry best practices:
    - GitHub Actions action.yml: explicit 'main' field
    - npm package.json: explicit 'main' field
    - Python pyproject.toml: explicit entry points
    - Google Gemini: "strong schema" principle
    - MCP Specification: explicit schema declarations

    Args:
        source: The source filename to validate
        skill_type: The skill type ('query' or 'mutation')
        path: Path to skill_def.md (for error messages)

    Raises:
        ValueError: If source filename is invalid or suffix mismatches type
    """
    if not source or not isinstance(source, str):
        raise ValueError(
            f"Missing or empty 'source' field in {path}. "
            f"Each skill_def.md must explicitly declare its execution file "
            f"(e.g. source: query.sql)"
        )

    if len(source) > _SOURCE_FILENAME_MAX_LENGTH:
        raise ValueError(
            f"'source' filename too long in {path}: "
            f"max {_SOURCE_FILENAME_MAX_LENGTH} characters"
        )

    # Path traversal and hidden file prevention
    if "/" in source or "\\" in source:
        raise ValueError(
            f"'source' must be a filename, not a path (no / or \\) in {path}: "
            f"got '{source}'"
        )

    if source.startswith("."):
        raise ValueError(
            f"'source' must not start with '.' (no hidden files) in {path}: "
            f"got '{source}'"
        )

    if not _SOURCE_FILENAME_PATTERN.match(source):
        raise ValueError(
            f"'source' filename contains invalid characters in {path}: "
            f"'{source}' — must match {_SOURCE_FILENAME_PATTERN.pattern}"
        )

    # Enforce suffix matching based on skill type
    expected_suffix = _SOURCE_SUFFIX_MAP.get(skill_type)
    if expected_suffix and not source.endswith(expected_suffix):
        raise ValueError(
            f"'source' suffix mismatch in {path}: type '{skill_type}' "
            f"requires '{expected_suffix}' suffix, got '{source}'"
        )


# Allowed database type values (normalized to lowercase)
_VALID_DB_TYPES = {"mysql", "sqlite"}


def _merge_unique(*items: list[str]) -> list[str]:
    """Merge lists while preserving first-seen order."""
    merged: list[str] = []
    seen: set[str] = set()
    for values in items:
        for value in values:
            if value not in seen:
                merged.append(value)
                seen.add(value)
    return merged


def _parse_string_list_field(
    raw: Any,
    field_name: str,
    path: Path,
    *,
    normalize_lower: bool = False,
) -> list[str]:
    """
    Parse optional YAML scalar/list fields into a normalized string list.

    Empty or omitted fields return an empty list. A scalar string is accepted as
    a one-item list to keep skill_def.md authoring concise.
    """
    if raw is None:
        return []

    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list) and raw:
        values = raw
    else:
        raise ValueError(
            f"'{field_name}' must be a non-empty string or list in {path}"
        )

    parsed: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"'{field_name}' entries must be non-empty strings in {path}"
            )
        normalized = value.strip()
        parsed.append(normalized.lower() if normalize_lower else normalized)

    return _merge_unique(parsed)


def _parse_databases(
    raw: str | list | None, path: Path
) -> list[str] | None:
    """
    Parse and validate the optional 'databases' field from YAML frontmatter.

    Accepts a list of database type strings (e.g. [mysql, sqlite]).
    Returns None if field is omitted (meaning "all databases supported").
    """
    if raw is None:
        return None

    normalized = _parse_string_list_field(
        raw,
        "databases",
        path,
        normalize_lower=True,
    )
    invalid = set(normalized) - _VALID_DB_TYPES
    if invalid:
        raise ValueError(
            f"Invalid database type(s) in {path}: {sorted(invalid)}. "
            f"Valid: {sorted(_VALID_DB_TYPES)}"
        )

    return sorted(normalized)


def _parse_skill_md(path: Path, dir_name: str) -> SkillMetadata:
    """
    Parse a skill_def.md file and return SkillMetadata.

    Uses '---' delimiter to extract YAML frontmatter, then yaml.safe_load().
    No dependency on python-frontmatter library.

    Args:
        path: Path to skill_def.md file
        dir_name: Directory name (used as fallback skill name)

    Returns:
        SkillMetadata instance

    Raises:
        ValueError: If frontmatter is missing or malformed
    """
    content = path.read_text(encoding="utf-8")
    parts = content.split("---", 2)

    if len(parts) < 3:
        raise ValueError(
            f"Invalid skill_def.md format: expected YAML frontmatter between "
            f"'---' delimiters in {path}"
        )

    try:
        front = yaml.safe_load(parts[1])
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML frontmatter in {path}: {e}") from e

    if not isinstance(front, dict):
        raise ValueError(f"YAML frontmatter must be a mapping in {path}")

    # Validate required fields
    for required_field in ("name", "type", "risk", "source"):
        if required_field not in front:
            raise ValueError(
                f"Missing required field '{required_field}' in {path}"
            )

    skill_name = _validate_skill_identity(front["name"], dir_name, path)

    skill_type = front["type"]
    if skill_type not in ("query", "mutation"):
        raise ValueError(
            f"Invalid type '{skill_type}' in {path}: must be 'query' or 'mutation'"
        )

    risk = front["risk"]
    if risk not in ("low", "medium", "high"):
        raise ValueError(
            f"Invalid risk '{risk}' in {path}: must be 'low', 'medium', or 'high'"
        )

    # Validate source filename (security: path traversal, hidden files, suffix)
    source = front["source"]
    _validate_source_filename(source, skill_type, path)

    return SkillMetadata(
        name=skill_name,
        type=skill_type,
        source=source,
        risk=risk,
        description=front.get("description", "").strip(),
        params=_validate_param_schema(front.get("params", {}), path),
        triggers=front.get("triggers", []),
        version=str(front.get("version", "1.0")),
        enabled=front.get("enabled", True),
        idempotent=front.get("idempotent", False),
        requires_confirmation=front.get("requires_confirmation", False),
        category=front.get("category"),
        related_skills=front.get("related_skills", []),
        databases=_parse_databases(front.get("databases"), path),
        profiles=_parse_string_list_field(
            front.get("profiles"),
            "profiles",
            path,
            normalize_lower=True,
        ),
        tables=_parse_string_list_field(
            front.get("tables"),
            "tables",
            path,
        ),
    )


def _load_mutation_class(skill_name: str, mutation_path: Path) -> type:
    """
    Dynamically import a mutation source module and return the Mutation class.

    Called by discover() at startup to pre-load and cache mutation classes.
    This eliminates per-invocation disk I/O and module compilation.

    Args:
        skill_name: Name of the mutation skill (for error messages)
        mutation_path: Path to the mutation source file

    Returns:
        The Mutation class (subclass of MutationBase)

    Raises:
        ImportError: If the source module cannot be imported
        AttributeError: If the source module doesn't export 'Mutation' class
        TypeError: If Mutation is not a concrete MutationBase subclass
    """
    spec = importlib.util.spec_from_file_location(
        f"skills.{skill_name}.mutation",
        mutation_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(
            f"Skill '{skill_name}': cannot load module spec from {mutation_path}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    mutation_class = getattr(module, "Mutation", None)
    if mutation_class is None:
        raise AttributeError(
            f"Skill '{skill_name}': source module must export a class named "
            "'Mutation' (subclass of MutationBase)"
        )

    if not inspect.isclass(mutation_class):
        raise TypeError(
            f"Skill '{skill_name}': source module export 'Mutation' must be a class"
        )

    from mutation_base import MutationBase

    if not issubclass(mutation_class, MutationBase):
        raise TypeError(
            f"Skill '{skill_name}': Mutation must subclass MutationBase"
        )

    if inspect.isabstract(mutation_class):
        raise TypeError(
            f"Skill '{skill_name}': Mutation must implement all MutationBase "
            "abstract methods"
        )

    return mutation_class


def _validate_param_schema(raw_params: Any, path: Path) -> dict[str, dict]:
    """
    Validate the lightweight frontmatter params schema vocabulary.

    This is not JSON Schema, but malformed skill definitions should still fail
    closed instead of silently accepting unsupported type names.
    """
    if raw_params is None:
        return {}

    if not isinstance(raw_params, dict):
        raise ValueError(f"'params' must be a mapping in {path}")

    validated_params: dict[str, dict] = {}
    for param_name, constraints in raw_params.items():
        if not isinstance(param_name, str) or not param_name.strip():
            raise ValueError(
                f"'params' keys must be non-empty strings in {path}"
            )

        if not isinstance(constraints, dict):
            raise ValueError(
                f"Parameter '{param_name}' schema must be a mapping in {path}"
            )

        expected_type = constraints.get("type", "str")
        if expected_type not in _SUPPORTED_PARAM_TYPES:
            raise ValueError(
                f"Unsupported param type '{expected_type}' for '{param_name}' in {path}. "
                f"Supported: {sorted(_SUPPORTED_PARAM_TYPES)}"
            )

        validated_params[param_name] = constraints

    return validated_params


def _extract_table_names(sql: str) -> list[str]:
    """
    Extract table names from a SQL template for documentation/review purposes.

    Handles common patterns: FROM table, JOIN table.
    Not a security mechanism — for SKILLS.md generation only.

    Args:
        sql: SQL template string

    Returns:
        Sorted list of unique table names found
    """
    pattern = r"(?:FROM|JOIN)\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?"
    matches = re.findall(pattern, sql, re.IGNORECASE)
    return sorted(set(matches))


def _coerce_type(param_name: str, value, expected_type: str):
    """
    Coerce/validate a parameter value to the expected type.

    Args:
        param_name: Name of the parameter (for error messages)
        value: The value to coerce
        expected_type: Expected type string ('int', 'float', 'str', 'bool')

    Returns:
        Coerced value

    Raises:
        TypeError: If coercion fails
        ValueError: If schema declares an unsupported type name
    """
    if expected_type not in _SUPPORTED_PARAM_TYPES:
        raise ValueError(
            f"Parameter '{param_name}': unsupported schema type '{expected_type}'. "
            f"Supported: {sorted(_SUPPORTED_PARAM_TYPES)}"
        )

    if expected_type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value in _JSON_BOOL_STRING_MAP:
            return _JSON_BOOL_STRING_MAP[value]
        raise TypeError(
            f"Parameter '{param_name}': expected type 'bool', "
            f"got {type(value).__name__} ({value!r})"
        )

    type_map = {
        "int": int,
        "float": float,
        "str": str,
    }

    python_type = type_map[expected_type]

    if isinstance(value, python_type):
        return value

    try:
        return python_type(value)
    except (ValueError, TypeError) as e:
        raise TypeError(
            f"Parameter '{param_name}': expected type '{expected_type}', "
            f"got {type(value).__name__} ({value!r})"
        ) from e
