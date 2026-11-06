"""Explicit service-instance lifecycle, with no ambient deployment configuration."""

from pathlib import Path
from functools import lru_cache
from contextlib import contextmanager
from contextvars import ContextVar
import threading
import time
import logging
from typing import Literal

logger = logging.getLogger(__name__)

from sql_safety_executor.config import AppConfig
from sql_safety_executor.database.registry import ConnectionRegistry
from sql_safety_executor.database.diagnostics import ConnectionDiagnostics
from sql_safety_executor.observability.audit import AuditLogger
from sql_safety_executor.skills.catalog import SkillCatalog, SkillReloadError, skill_signature
from .preview_tokens import InMemoryPreviewTokenStore
from .policy import _validate_sql_template_startup_policy
from .managed_sql import check_managed_sql
from .types import OperationError

_MANAGED_PLAN_CLASSIFICATION_CACHE_SIZE = 128


class GatewayRuntime:
    def __init__(self, config: AppConfig):
        self.config = config
        # Only immutable, pure classification decisions are retained. The key
        # contains verbatim SQL, the complete frozen DialectContext
        # and (for full managed checks) the immutable declared bind-name set.
        # Context resolution, authorization, readiness and tokens stay uncached.
        self.classify_managed_plan = lru_cache(
            maxsize=_MANAGED_PLAN_CLASSIFICATION_CACHE_SIZE
        )(check_managed_sql)
        self.registry = ConnectionRegistry(
            config.connections, config.server.server.default_connection
        )
        self._catalog = SkillCatalog()
        self._catalog_snapshot: ContextVar[SkillCatalog | None] = ContextVar(
            "skill_catalog_snapshot", default=None
        )
        self._reload_lock = threading.Lock()
        # Held only for publication and proposal admission, never for Python
        # loading, callbacks, database work or an await.
        self._publication_lock = threading.RLock()
        self.catalog_revision = 0
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

    @property
    def catalog(self) -> SkillCatalog:
        return self._catalog_snapshot.get() or self._catalog

    @contextmanager
    def catalog_snapshot(self):
        """Bind all lookups in one MCP request to the same published catalog."""
        token = self._catalog_snapshot.set(self.catalog)
        try:
            yield
        finally:
            self._catalog_snapshot.reset(token)

    @contextmanager
    def mutation_generation_guard(self, skill_name: str, generation: str | None):
        """Linearize proposal issuance/consumption against catalog publication."""
        with self._publication_lock:
            current = self._catalog.get_skills_cache().get(skill_name)
            if (
                not generation
                or current is None
                or current.type != "mutation"
                or current._mutation_generation != generation
            ):
                raise OperationError(
                    "Mutation definition changed or was removed before execution; "
                    "this proposal was not admitted. The previous preview is no longer "
                    "valid. Let the user decide whether to preview again."
                )
            yield

    def reload_skills(self, skill_type: Literal["query", "mutation"] = "query") -> dict:
        """Stage one Skill kind and publish once, preserving the other kind."""
        if skill_type not in {"query", "mutation"}:
            raise SkillReloadError("", "invalid_skill_type")
        if skill_type == "mutation" and not self.config.skills.mutation.enabled:
            raise SkillReloadError("", "mutation_reload_disabled")
        if not self._reload_lock.acquire(blocking=False):
            raise SkillReloadError("", "reload_in_progress")
        try:
            previous = self._catalog.get_skills_cache()
            preserved = {name: meta for name, meta in previous.items() if meta.type != skill_type}
            old_selected = {name for name, meta in previous.items() if meta.type == skill_type}
            directory = Path(self.config.skills.directory)
            candidate = SkillCatalog()
            selected = candidate.discover(
                directory,
                query_validator=lambda sql: _validate_sql_template_startup_policy(self, sql),
                load_mutations=skill_type == "mutation",
                query_only=skill_type == "query",
                mutation_only=skill_type == "mutation",
                strict=True,
                skip_names=frozenset(preserved),
                required_definitions=frozenset(old_selected),
                reuse_mutations=previous if skill_type == "mutation" else None,
            )
            ignored = candidate.ignored_mutations if skill_type == "query" else candidate.ignored_queries
            for name in ignored:
                if name in previous and previous[name].type == skill_type:
                    raise SkillReloadError(name, "skill_type_change_requires_restart")
            added = sorted(selected.keys() - old_selected)
            removed = sorted(old_selected - selected.keys())
            changed = []
            for name in selected.keys() & old_selected:
                if skill_signature(selected[name]) != skill_signature(previous[name]):
                    changed.append(name)
                else:
                    selected[name] = previous[name]
            selected.update(preserved)
            invalidated = 0
            with self._publication_lock:
                if added or changed or removed:
                    if skill_type == "mutation":
                        invalidated = self.tokens.discard_skills(
                            set(changed) | set(removed), now=int(time.time())
                        )
                    self._catalog = candidate
                    self.catalog_revision += 1
            return {
                "success": True, "revision": self.catalog_revision, "skill_type": skill_type,
                "added": added, "changed": sorted(changed), "removed": removed,
                ("preserved_mutations" if skill_type == "query" else "preserved_queries"): sorted(preserved),
                ("ignored_new_mutations" if skill_type == "query" else "ignored_new_queries"): sorted(ignored),
                "invalidated_previews": invalidated,
                "hint": (
                    "Check this receipt and re-read affected Skill details in the actual consumer. "
                    "Use task-relevant execution to verify changed behavior when needed. "
                    + ("Mutation definitions and previews were preserved. " if skill_type == "query" else
                       "Pending previews for changed/removed Mutations are invalid; the user must decide whether to preview again. "
                       "Already admitted executions may finish on their original version. ")
                    + "Shared Python dependencies, connections and authorization were not reloaded."
                ),
            }
        finally:
            self._reload_lock.release()

    def start(self) -> None:
        self.diagnostics.start()

    def close(self) -> None:
        try:
            self.diagnostics.close()
        finally:
            try:
                self.registry.close()
            finally:
                self.tokens.clear()
                self.classify_managed_plan.cache_clear()
