"""Explicit adapter factories for regression fixtures; no application globals."""

from sql_safety_executor.database.models import ConnectionPolicy, DatabaseConfig
from sql_safety_executor.database.outcomes import *
from sql_safety_executor.database.sqlite import SQLiteAdapter as NativeSQLiteAdapter
from sql_safety_executor.database.mysql import MySQLAdapter as NativeMySQLAdapter
from pydantic import SecretStr
from tests.support import SCENARIO


def sqlite_config(path=":memory:"):
    return DatabaseConfig(
        "default",
        "sqlite",
        30,
        10,
        ConnectionPolicy(allowed_tables=frozenset({"*"}), read_mode="all"),
        sqlite_database_path=str(path),
    )


def SQLiteAdapter(database_path=None, *, config=None, diagnostic=False):
    return NativeSQLiteAdapter(
        config=config
        or sqlite_config(
            database_path or SCENARIO.get("SQLITE_DATABASE_PATH", ":memory:")
        ),
        diagnostic=diagnostic,
    )


def MySQLAdapter(config=None, *, diagnostic=False):
    return NativeMySQLAdapter(
        config
        or DatabaseConfig(
            "default",
            "mysql",
            30,
            10,
            ConnectionPolicy(),
            mysql_host=SCENARIO.get("DB_HOST") or "localhost",
            mysql_user=SCENARIO.get("DB_USER") or "fixture",
            mysql_password=SecretStr(SCENARIO.get("DB_PASSWORD") or "fixture"),
            mysql_database=SCENARIO.get("DB_NAME") or "fixture",
        ),
        diagnostic=diagnostic,
    )


def reset_adapter():
    pass

from sql_safety_executor.database.registry import CONNECTION_ID_PATTERN as CONNECTION_ID_PATTERN
from sql_safety_executor.database.registry import create_adapter as create_adapter
from sql_safety_executor.database.registry import ConnectionRegistry as ConnectionRegistry
