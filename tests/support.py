"""Explicit fixtures for migrated regressions, never imported by the application.

SCENARIO is a test data dictionary (historical field labels), not os.environ.
Each factory writes three isolated TOMLs and invokes the real strict loader.
GatewayView binds the formerly module-level test calls to an instance; it does
not implement policy, execution, token handling, or protocol behavior.
"""

from __future__ import annotations
import functools
import importlib
import inspect
import json
import tempfile
from dataclasses import replace
from pathlib import Path

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core import types
from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig

ROOT = Path(__file__).resolve().parent.parent
SCENARIO = {}
LIVE = []
MODULES = [
    importlib.import_module("sql_safety_executor." + p)
    for p in (
        "core.policy",
        "core.results",
        "core.connections",
        "core.proposals",
        "core.queries",
        "core.schema",
        "core.diagnostics",
        "core.mutations",
        "skills.access",
        "skills.tools",
        "core.sql",
        "core.constants",
    )
]
FIELDS = {
    "ENABLE_SCHEMA_TOOLS": "server.tools.schema_enabled",
    "ENABLE_TABLE_SUMMARY": "server.tools.table_summary",
    "LARGE_TABLE_THRESHOLD": "server.tools.large_table_threshold",
    "MAX_RESULT_ROWS": "server.limits.result_rows",
    "MAX_RESULT_CHARS": "server.limits.result_chars",
    "MAX_SQL_LENGTH": "server.limits.sql_chars",
    "MAX_SCHEMA_TABLES": "server.limits.schema_tables",
    "MAX_OVERVIEW_TABLES": "server.limits.overview_tables",
    "SKILLS_CHECK_SCHEMA_ON_LIST": "skills.readiness.check_schema",
    "SKILLS_LIST_AVAILABLE_ONLY_DEFAULT": "skills.discovery.available_only",
    "SKILLS_LIST_DEFAULT_DETAIL": "skills.discovery.default_detail",
    "SKILLS_EXCLUDE_PROFILES": "skills.policy.exclude_profiles",
    "MUTATION_PREVIEW_TOKEN_TTL_SECONDS": "skills.mutation.preview.ttl_seconds",
    "TOOL_TELEMETRY_SAMPLE_RATE": "server.observability.telemetry.sample_rate",
}


def toml_value(value):
    if isinstance(value, dict):
        return (
            "{"
            + ", ".join(json.dumps(k) + " = " + toml_value(v) for k, v in value.items())
            + "}"
        )
    if isinstance(value, (tuple, list)):
        return "[" + ", ".join(map(toml_value, value)) + "]"
    return json.dumps(value, ensure_ascii=False)


def write_toml(path, data):
    path.write_text(
        "\n".join(json.dumps(k) + " = " + toml_value(v) for k, v in data.items()),
        encoding="utf-8",
    )


def config_from_scenario(directory):
    e = SCENARIO
    boolean = lambda key, default=False: (
        str(e.get(key, "1" if default else "0")).lower() in ("1", "true")
    )
    integer = lambda key, default: int(e.get(key, default))
    csv = lambda key: [
        x.strip().lower() for x in str(e.get(key, "")).split(",") if x.strip()
    ]
    aliases = csv("DB_CONNECTIONS") or ["default"]
    default = e.get("DEFAULT_DB_CONNECTION") or aliases[0]
    mutation = boolean("SKILLS_ALLOW_MUTATIONS")
    skills_enabled = boolean("ENABLE_SKILLS")
    admitted = csv("SKILLS_ALLOW_MUTATION_CONNECTIONS")
    # Existing single-target scenarios explicitly grant their fixture target writes.
    if mutation and not admitted and not csv("DB_CONNECTIONS"):
        admitted = [default]
    conns = {}
    for alias in aliases:
        prefix = "DB_" + alias.upper() + "_" if csv("DB_CONNECTIONS") else ""
        typ = e.get(prefix + "TYPE" if prefix else "DB_TYPE", "sqlite")
        tables = csv(prefix + "ALLOWED_TABLES")
        # Historical unrestricted read fixtures are explicitly read.mode=all.
        read = {
            "mode": "all" if not tables or tables == ["*"] else "allowlist",
            "allow_union": boolean(prefix + "ALLOW_UNION"),
        }
        if read["mode"] == "allowlist":
            read["tables"] = tables
        c = {
            "type": typ,
            "read": read,
            "timeouts": {
                "query_seconds": integer(
                    prefix + "QUERY_TIMEOUT_SECONDS",
                    integer("QUERY_TIMEOUT_SECONDS", 30),
                ),
                "connect_seconds": integer(
                    prefix + "CONNECT_TIMEOUT_SECONDS",
                    integer("CONNECT_TIMEOUT_SECONDS", 10),
                ),
            },
            "mutation": {
                "enabled": boolean(
                    prefix + "ALLOW_MUTATIONS", mutation and alias in admitted
                ),
                "skills": csv(prefix + "MUTATION_SKILLS")
                or (["*"] if mutation and alias in admitted else []),
            },
        }
        if typ == "sqlite":
            c["sqlite"] = {
                "path": e.get(prefix + "SQLITE_DATABASE_PATH", ":memory:"),
                "progress_handler_interval": integer(
                    prefix + "SQLITE_PROGRESS_HANDLER_INTERVAL", 100
                ),
            }
        else:
            c["mysql"] = {
                key: e.get(prefix + suffix if prefix else "DB_" + suffix) or "fixture"
                for key, suffix in [
                    ("host", "HOST"),
                    ("user", "USER"),
                    ("database", "NAME"),
                ]
            }
            c["mysql"]["password"] = {
                "value": e.get(prefix + "PASSWORD" if prefix else "DB_PASSWORD")
                or "fixture"
            }
        conns[alias] = c
    main = {
        "schema_version": 1,
        "files": {"connections": "connections.toml", "skills": "skills.toml"},
        "server": {
            "default_connection": default,
            "tool_timeout_seconds": float(e.get("MCP_TOOL_TIMEOUT_SECONDS", 120)),
        },
        "tools": {
            "schema": boolean("ENABLE_SCHEMA_TOOLS", True),
            "table_summary": boolean("ENABLE_TABLE_SUMMARY"),
            "large_table_threshold": integer("LARGE_TABLE_THRESHOLD", 1000),
        },
        "limits": {
            field: integer(key, default)
            for field, key, default in [
                ("result_rows", "MAX_RESULT_ROWS", 100),
                ("result_chars", "MAX_RESULT_CHARS", 16000),
                ("sql_chars", "MAX_SQL_LENGTH", 20000),
                ("schema_tables", "MAX_SCHEMA_TABLES", 50),
                ("overview_tables", "MAX_OVERVIEW_TABLES", 100),
            ]
        },
        "observability": {
            "telemetry": {
                "enabled": boolean("ENABLE_TOOL_TELEMETRY"),
                "path": e.get(
                    "TOOL_TELEMETRY_LOG_PATH", str(directory / "telemetry.jsonl")
                ),
                "sample_rate": float(e.get("TOOL_TELEMETRY_SAMPLE_RATE", 1)),
            }
        },
    }
    skill = {
        "schema_version": 1,
        "skills": {
            "enabled": skills_enabled,
            "directory": str(
                Path(e.get("SKILLS_DIR", str(ROOT / "skills"))).absolute()
            ),
            "discovery": {
                "default_detail": e.get("SKILLS_LIST_DEFAULT_DETAIL", "summary"),
                "available_only": boolean("SKILLS_LIST_AVAILABLE_ONLY_DEFAULT", True),
            },
            "readiness": {"check_schema": boolean("SKILLS_CHECK_SCHEMA_ON_LIST", True)},
            "policy": {"exclude_profiles": csv("SKILLS_EXCLUDE_PROFILES")},
            "audit": {
                "path": e.get("SKILLS_AUDIT_LOG", str(directory / "audit.jsonl")),
                "queries": boolean("SKILLS_AUDIT_QUERIES"),
            },
            "mutation": {
                "enabled": mutation,
                "allowed_connections": admitted,
                "preview": {
                    "ttl_seconds": integer("MUTATION_PREVIEW_TOKEN_TTL_SECONDS", 300),
                    "max_entries": integer(
                        "MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES", 10000
                    ),
                },
            },
        },
    }
    for name, data in [
        ("server", main),
        ("connections", {"schema_version": 1, "connections": conns}),
        ("skills", skill),
    ]:
        write_toml(directory / (name + ".toml"), data)
    return load_config(directory / "server.toml")


class GatewayView:
    def __init__(self, config):
        object.__setattr__(self, "mcp", create_server(config))
        object.__setattr__(self, "runtime", self.mcp.gateway_runtime)

    def __getattr__(self, name):
        r = self.runtime
        aliases = {
            "get_adapter": r.registry.get_adapter,
            "get_database_config": r.registry.get_config,
            "get_database_configs": r.registry.list_configs,
            "list_connection_configs": r.registry.list_configs,
            "get_connection_config": r.registry.get_config,
            "get_default_connection_id": r.default_connection_id,
            "get_skills_cache": r.catalog.get_skills_cache,
            "load_query": r.catalog.load_query,
            "load_mutation": r.catalog.load_mutation,
            "_audit_logger": r.audit,
            "_MUTATION_PREVIEW_TOKEN_STORE": r.tokens,
            "_mutation_preview_token_store": r.tokens,
            "_connection_diagnostics": r.diagnostics,
            "ConnectionPolicy": ConnectionPolicy,
            "DatabaseConfig": DatabaseConfig,
            "ToolError": types.OperationError,
        }
        if name in aliases:
            return aliases[name]
        if name == "_ToolTelemetryMiddleware":
            from sql_safety_executor.observability.telemetry import (
                ToolTelemetryMiddleware,
            )

            def make_telemetry(log_path=None, sample_rate=None):
                from dataclasses import replace

                settings = r.config.server.observability.telemetry
                changes = {}
                if log_path is not None:
                    changes["path"] = str(log_path)
                if sample_rate is not None:
                    changes["sample_rate"] = sample_rate
                r.config = replace(
                    r.config,
                    server=r.config.server.model_copy(
                        update={
                            "observability": r.config.server.observability.model_copy(
                                update={
                                    "telemetry": settings.model_copy(update=changes)
                                }
                            )
                        }
                    ),
                )
                return ToolTelemetryMiddleware(r)

            return make_telemetry
        if name == "sql_assistant":
            from sql_safety_executor.prompts.render import assistant

            return lambda: assistant(r.config)
        if name == "lifespan":
            return self.mcp._lifespan
        if name == "execute_mutation_skill" and not r.config.skills.mutation.enabled:
            raise AttributeError(name)
        if name == "_CONNECTION_ROUTING_GUIDANCE":
            from sql_safety_executor.prompts.render import text

            return text("routing.md")
        if name in ("MCP_TOOL_TIMEOUT", "_MCP_TOOL_TIMEOUT"):
            return r.tool_timeout
        if name == "MUTATION_PREVIEW_TOKEN_STORE_MAX_ENTRIES":
            return r.config.skills.mutation.preview.max_entries
        if name in FIELDS:
            val = r.config
            for field in FIELDS[name].split("."):
                val = getattr(val, field)
            return val
        for module in MODULES:
            if hasattr(module, name):
                value = getattr(module, name)
                if (
                    inspect.isfunction(value)
                    and next(iter(inspect.signature(value).parameters), None)
                    == "runtime"
                ):
                    bound = functools.partial(value, r)
                    functools.update_wrapper(bound, value)
                    if name == "list_skills":
                        bound.keywords.update(
                            detail_level=r.config.skills.discovery.default_detail,
                            available_only=r.config.skills.discovery.available_only,
                        )
                    return bound
                return value
        raise AttributeError(name)

    def __setattr__(self, name, value):
        r = self.runtime
        if name in FIELDS:
            chain = FIELDS[name].split(".")

            def update(obj, fields):
                if not fields:
                    return value
                child = update(getattr(obj, fields[0]), fields[1:])
                return (
                    obj.model_copy(update={fields[0]: child})
                    if hasattr(obj, "model_copy")
                    else replace(obj, **{fields[0]: child})
                )

            r.config = update(r.config, chain)
            return
        if name == "_connection_diagnostics":
            r.diagnostics = value
            return
        if name == "_MCP_TOOL_TIMEOUT":
            r.tool_timeout = value
            return
        if name == "list_connection_configs":
            r.registry.list_configs = value
            return
        if name == "get_connection_config":
            r.registry.get_config = value
            return
        if name == "get_adapter":
            r.registry.get_adapter = value
            return
        if name == "load_mutation":
            r.catalog.load_mutation = value
            return
        if name == "load_query":
            r.catalog.load_query = value
            return
        if name == "_audit_logger":
            r.audit = value
            return
        original = getattr(self, name)
        found = False
        for module in MODULES:
            if hasattr(module, name):
                old = getattr(module, name)
                stateful = (
                    inspect.isfunction(old)
                    and next(iter(inspect.signature(old).parameters), None) == "runtime"
                    or getattr(old, "_test_runtime_wrapper", False)
                )
                if isinstance(value, functools.partial):
                    setattr(module, name, value.func)
                elif stateful:

                    def wrapped(runtime, *a, _value=value, **kw):
                        return _value(*a, **kw)

                    wrapped._test_runtime_wrapper = True
                    setattr(module, name, wrapped)
                else:
                    setattr(module, name, value)
                found = True
        if not found:
            object.__setattr__(self, name, value)


def make_gateway():
    directory = tempfile.TemporaryDirectory(prefix="sql-regression-")
    try:
        gateway = GatewayView(config_from_scenario(Path(directory.name)))
    except BaseException:
        directory.cleanup()
        raise
    LIVE.append((gateway, directory))
    return gateway


def cleanup():
    while LIVE:
        gateway, directory = LIVE.pop()
        gateway.runtime.close()
        directory.cleanup()
