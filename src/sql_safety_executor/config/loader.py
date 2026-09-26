from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import BaseModel, SecretStr, ValidationError

from sql_safety_executor.database.models import DatabaseConfig

from .models import ConnectionsFile, SecretSource, ServerFile, Skills, SkillsFile


class ConfigError(ValueError):
    """Only sanitized file/field/category information may cross this boundary."""


@dataclass(frozen=True)
class AppConfig:
    path: Path
    server: ServerFile
    skills: Skills
    connections: Mapping[str, DatabaseConfig]
    sources: Mapping[str, str]
    explanation: Mapping[str, Any]


def _read(path: Path, schema):
    try:
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: configuration_file_{type(exc).__name__}") from None
    # Literal[1] alone accepts True/1.0 through Python equality.
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
        raise ConfigError(f"{path}: schema_version: unsupported_version")
    try:
        return schema.model_validate(raw), raw
    except ValidationError as exc:
        errors = [
            f"{'.'.join(map(str, e['loc']))}: {e['type']}"
            for e in exc.errors(
                include_input=False, include_context=False, include_url=False
            )
        ]
        raise ConfigError(f"{path}: " + "; ".join(errors)) from None


def _path(value: str, source: Path) -> str:
    candidate = Path(value)
    return str(
        (candidate if candidate.is_absolute() else source.parent / candidate).resolve()
    )


def _secret(source: SecretSource, file: Path, field: str) -> SecretStr:
    try:
        if source.value is not None:
            value = source.value.get_secret_value()
        elif source.env is not None:
            value = os.environ[source.env]
        else:
            assert source.file is not None
            with Path(_path(source.file, file)).open("rb") as stream:
                raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError("secret_too_large")
            value = raw.decode("utf-8")
        if not value:
            raise ValueError("empty_secret")
        return SecretStr(value)
    except (OSError, KeyError, UnicodeError, ValueError):
        raise ConfigError(f"{file}: {field}: secret_unavailable_or_invalid") from None


def _flatten(value, prefix=""):
    if isinstance(value, BaseModel):
        value = {
            field.alias or name: getattr(value, name)
            for name, field in type(value).model_fields.items()
        }
    if isinstance(value, SecretSource):  # kept for callers passing raw objects
        yield prefix, "<redacted>"
    elif isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key == "password":
                yield path, "<redacted>"
            else:
                yield from _flatten(child, path)
    elif isinstance(value, SecretStr):
        yield prefix, "<redacted>"
    else:
        yield prefix, value


def load_config(path: str | Path) -> AppConfig:
    """Validate a complete snapshot; never import Skill implementations or connect."""
    from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig

    main = Path(path).resolve()
    server, raw_server = _read(main, ServerFile)
    connections_path = Path(_path(server.files.connections, main))
    connections, raw_connections = _read(connections_path, ConnectionsFile)
    if server.server.default_connection not in connections.connections:
        raise ConfigError(f"{main}: server.default_connection: unknown_connection")
    skills_path = (
        Path(_path(server.files.skills, main)) if server.files.skills else main
    )
    skills_file, raw_skills = (
        _read(skills_path, SkillsFile)
        if server.files.skills
        else (SkillsFile(schema_version=1), {})
    )
    skills = skills_file.skills
    if any(
        alias not in connections.connections
        for alias in skills.mutation.allowed_connections
    ):
        raise ConfigError(
            f"{skills_path}: skills.mutation.allowed_connections: unknown_connection"
        )
    skills = skills.model_copy(
        update={
            "directory": _path(skills.directory, skills_path),
            "audit": skills.audit.model_copy(
                update={"path": _path(skills.audit.path, skills_path)}
            ),
        }
    )
    if skills.enabled and not Path(skills.directory).is_dir():
        raise ConfigError(f"{skills_path}: skills.directory: directory_not_found")
    observability = server.observability.model_copy(
        update={
            "telemetry": server.observability.telemetry.model_copy(
                update={"path": _path(server.observability.telemetry.path, main)}
            ),
            "logging": server.observability.logging.model_copy(
                update={
                    "path": _path(server.observability.logging.path, main)
                    if server.observability.logging.path
                    else None
                }
            ),
        }
    )
    server = server.model_copy(update={"observability": observability})
    configs = {}
    explanation = {}
    sources = {}
    for model, raw, file in (
        (server, raw_server, main),
        (connections, raw_connections, connections_path),
        (skills, raw_skills.get("skills", {}), skills_path),
    ):
        prefix = "skills" if isinstance(model, Skills) else ""
        explicit = dict(_flatten(raw, prefix))
        for field, value in _flatten(model, prefix):
            explanation[field] = value
            sources[field] = str(file) if field in explicit else "builtin_default"
    for alias, connection in connections.connections.items():
        policy = ConnectionPolicy(
            allow_union=connection.read.allow_union,
            allowed_tables=frozenset({"*"})
            if connection.read.mode == "all"
            else frozenset(t.lower() for t in connection.read.tables),
            allow_mutations=connection.mutation.enabled,
            mutation_skills=frozenset(connection.mutation.skills),
            read_mode=connection.read.mode,
        )
        timeouts = {}
        for key in ("query_seconds", "connect_seconds"):
            value = getattr(connection.timeouts, key)
            field = f"connections.{alias}.timeouts.{key}"
            explanation[field] = (
                value if value is not None else getattr(server.defaults.timeouts, key)
            )
            if value is None:
                sources[field] = (
                    sources[f"defaults.timeouts.{key}"]
                    + f" via defaults.timeouts.{key}"
                )
            timeouts[key] = explanation[field]
        values: dict[str, Any] = dict(
            connection_id=alias,
            db_type=connection.type,
            query_timeout_seconds=timeouts["query_seconds"],
            connect_timeout_seconds=timeouts["connect_seconds"],
            policy=policy,
        )
        if connection.mysql:
            field = f"connections.{alias}.mysql.password"
            values.update(
                mysql_user=connection.mysql.user,
                mysql_host=connection.mysql.host,
                mysql_database=connection.mysql.database,
                mysql_password=_secret(
                    connection.mysql.password, connections_path, field
                ),
            )
            sources[field] = "secret:" + (
                "value"
                if connection.mysql.password.value is not None
                else "env"
                if connection.mysql.password.env
                else "file"
            )
            explanation[field] = "<redacted: provided>"
        else:
            assert connection.sqlite is not None
            db_path = connection.sqlite.path
            values.update(
                sqlite_database_path=db_path
                if db_path == ":memory:"
                else _path(db_path, connections_path),
                sqlite_progress_handler_interval=connection.sqlite.progress_handler_interval,
            )
            explanation[f"connections.{alias}.sqlite.path"] = values[
                "sqlite_database_path"
            ]
        configs[alias] = DatabaseConfig(**values)
    return AppConfig(
        main,
        server,
        skills,
        MappingProxyType(configs),
        MappingProxyType(sources),
        MappingProxyType(explanation),
    )


def explain_config(config: AppConfig) -> dict[str, Any]:
    result = {
        field: {"value": value, "source": config.sources[field]}
        for field, value in config.explanation.items()
    }
    result["effective.mutations"] = {}
    for alias, db in config.connections.items():
        gates = {
            "skills.enabled": config.skills.enabled,
            "skills.mutation.enabled": config.skills.mutation.enabled,
            "skills.mutation.allowed_connections": alias
            in config.skills.mutation.allowed_connections,
            f"connections.{alias}.mutation.enabled": db.policy.allow_mutations,
            f"connections.{alias}.mutation.skills": bool(db.policy.mutation_skills),
        }
        result["effective.mutations"][alias] = {
            "enabled": all(gates.values()),
            "disabled_reasons": [
                field for field, allowed in gates.items() if not allowed
            ],
            "requirements": "All configuration gates AND matching Skill allowlist AND execution checks",
        }
    result["effective.skills"] = {
        "enabled": config.skills.enabled,
        "disabled_reason": None
        if config.skills.enabled
        else "skills.enabled=false or no files.skills reference",
        "mrtr_enabled": config.skills.mutation.mrtr.enabled,
    }
    return result
