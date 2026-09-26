"""Explicit service-instance lifecycle, with no ambient deployment configuration."""

from pathlib import Path
import logging

logger = logging.getLogger(__name__)

from sql_safety_executor.config import AppConfig
from sql_safety_executor.database.registry import ConnectionRegistry
from sql_safety_executor.database.diagnostics import ConnectionDiagnostics
from sql_safety_executor.observability.audit import AuditLogger
from sql_safety_executor.skills.catalog import SkillCatalog
from .preview_tokens import InMemoryPreviewTokenStore
from .policy import _validate_sql_template_startup_policy


class GatewayRuntime:
    def __init__(self, config: AppConfig):
        self.config = config
        self.registry = ConnectionRegistry(
            config.connections, config.server.server.default_connection
        )
        self.catalog = SkillCatalog()
        self.tokens = InMemoryPreviewTokenStore(
            config.skills.mutation.preview.max_entries
        )
        self.diagnostics = ConnectionDiagnostics()
        self.audit = None
        self.tool_timeout = config.server.server.tool_timeout_seconds or None
        try:
            if config.skills.enabled:
                self.catalog.discover(
                    Path(config.skills.directory),
                    query_validator=lambda sql: _validate_sql_template_startup_policy(
                        self, sql
                    ),
                    load_mutations=config.skills.mutation.enabled,
                )
                for meta in self.catalog.get_skills_cache().values():
                    for alias in meta.connection_ids or ():
                        target = config.connections.get(alias)
                        if target is None:
                            logger.warning(
                                "Skill '%s' declares connection_ids not configured in this deployment: %s",
                                meta.name,
                                alias,
                            )
                        elif meta.databases and target.db_type not in meta.databases:
                            logger.error(
                                "Skill '%s' connection scope conflict: '%s' has database type '%s'; supports %s",
                                meta.name,
                                alias,
                                target.db_type,
                                meta.databases,
                            )
                self.audit = AuditLogger(
                    config.skills.audit.path, config.skills.audit.agent_id
                )
        except BaseException:
            self.close()
            raise

    def default_connection_id(self) -> str:
        return self.registry.default

    def start(self) -> None:
        self.diagnostics.start()

    def close(self) -> None:
        try:
            self.diagnostics.close()
        finally:
            self.registry.close()
            self.tokens.clear()
