"""Instance-owned, lazily constructed business adapters."""

from __future__ import annotations

import logging
import re
from threading import RLock
from typing import Mapping

from .base import DatabaseAdapter
from .models import DatabaseConfig
from .mysql import MySQLAdapter
from .sqlite import SQLiteAdapter

logger = logging.getLogger(__name__)
CONNECTION_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def create_adapter(
    *, config: DatabaseConfig, diagnostic: bool = False
) -> DatabaseAdapter:
    if config.db_type == "mysql":
        adapter = MySQLAdapter(config, diagnostic=diagnostic)
    elif config.db_type == "sqlite":
        adapter = SQLiteAdapter(config=config, diagnostic=diagnostic)
    else:
        raise ValueError("Unsupported database type")
    # Creating a registry entry must not perform I/O. Adapter operations connect
    # lazily; diagnostic workers retain ownership of their own connections.
    return adapter


class ConnectionRegistry:
    def __init__(self, configs: Mapping[str, DatabaseConfig], default: str):
        if default not in configs:
            raise ValueError("Default connection is not configured")
        self.configs = configs
        self.default = default
        self._adapters: dict[str, DatabaseAdapter] = {}
        self._lock = RLock()

    def get_config(self, connection_id: str | None = None) -> DatabaseConfig:
        alias = self.default if connection_id is None else connection_id
        if not isinstance(alias, str) or not CONNECTION_ID_PATTERN.fullmatch(
            alias.strip().lower()
        ):
            raise ValueError("Invalid connection_id")
        alias = alias.strip().lower()
        if alias not in self.configs:
            raise ValueError(f"Unknown connection_id '{alias}'")
        return self.configs[alias]

    def list_configs(self) -> list[DatabaseConfig]:
        return list(self.configs.values())

    def get_adapter(self, connection_id: str | None = None) -> DatabaseAdapter:
        config = self.get_config(connection_id)
        with self._lock:
            if config.connection_id not in self._adapters:
                self._adapters[config.connection_id] = create_adapter(config=config)
            return self._adapters[config.connection_id]

    def close(self) -> None:
        errors = []
        with self._lock:
            for adapter in self._adapters.values():
                try:
                    adapter.close()
                except Exception as exc:
                    errors.append(type(exc).__name__)
            self._adapters.clear()
        if errors:
            logger.warning("Adapter cleanup failures: %s", errors)
