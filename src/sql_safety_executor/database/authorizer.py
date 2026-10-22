"""SQLite compile-time checks scoped to one exclusively owned read operation."""
from __future__ import annotations

import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field

from .errors import DatabaseQueryError
from .identifiers import ascii_identifier_lower as fold
from .models import ConnectionPolicy
from .relations import RelationReference
from .semantics import DialectContext
from .sqlite_virtual import fts5_definition

PlanRead = tuple[str | None, str | None, str | None]  # table (None: source only), database, source


@dataclass
class SQLiteReadGuard:
    policy: ConnectionPolicy
    default_schema: str
    cte_names: frozenset[str] = frozenset()
    view_edges: set[tuple[str, RelationReference]] = field(default_factory=set)
    resolved_bindings: dict[str, set[RelationReference]] = field(default_factory=dict)
    ephemeral_ctes: frozenset[str] = frozenset()
    explain_dml: bool = False
    denial: str | None = None
    prepared_plan_reads: frozenset[PlanRead] = frozenset()
    pending_plan_reads: set[PlanRead] = field(default_factory=set)
    catalog_lookups: int = 0
    plan_count_sources: set[str] = field(default_factory=set)
    prepared_sources: set[str] = field(default_factory=set)
    trigger_cte_reads: set[tuple[str, str]] = field(default_factory=set)
    virtual_edges: set[tuple[str | None, RelationReference]] = field(default_factory=set)
    catalog_reads: set[RelationReference] = field(default_factory=set)
    module_roots: set[RelationReference] = field(default_factory=set)
    module_reads: set[RelationReference] = field(default_factory=set)
    module_columns: dict[RelationReference, set[str]] = field(default_factory=dict)
    module_pragmas: set[tuple[str, str]] = field(default_factory=set)

    def deny(self, code: str) -> int:
        if self.denial is None:
            self.denial = code
        return sqlite3.SQLITE_DENY

    def request_plan_read(self, name: str | None, database: str | None, source: str | None) -> bool:
        request = (fold(name) if name is not None else None, fold(database) if database is not None else None,
                   fold(source) if source is not None else None)
        if not self.explain_dml or request in self.prepared_plan_reads:
            return False
        self.pending_plan_reads.add(request)
        return True

    def authorize(self, action: int, first: str | None, second: str | None,
                  database: str | None, source: str | None) -> int:
        from sql_safety_executor.core.read_rules import (
            restricted_function_code, _SQLITE_PRAGMA_OBJECTS,
        )
        if action == sqlite3.SQLITE_READ:
            if first is None:
                return self.deny("table_access_denied")
            if fold(first) in _SQLITE_PRAGMA_OBJECTS:
                return self.deny("server_state_denied")
            unscoped_count = database is None and second == "" and (
                source is None or not self.explain_dml and fold(source) in self.cte_names
                or self.explain_dml and fold(source) in self.plan_count_sources
            )
            if database is None:
                # Materialized/constant CTE counts can emit an empty-column
                # READ of the CTE itself. This is not a physical relation grant:
                # bootstrap verified a unique declaration and no catalog object
                # with that spelling; all actual base READs remain checked.
                if second == "" and (fold(first) in self.ephemeral_ctes or (
                    self.explain_dml and source is not None
                    and (fold(first), fold(source)) in self.trigger_cte_reads
                )):
                    return sqlite3.SQLITE_OK
                # A trigger can introduce a relation absent from the outer
                # statement. Resolve all matching catalogs outside this callback
                # before accepting its database-less count, including shadows.
                if self.request_plan_read(first, database, source):
                    return self.deny("view_scope_unresolved")
                # SQLite emits extra empty-column READ events without a DB
                # for some rowid/count/order plans. Bind only to a unique
                # catalog-resolved object from this analysis, never guess main.
                candidates = self.resolved_bindings.get(fold(first), set())
                if len(candidates) != 1:
                    return self.deny("view_scope_unresolved")
                database = next(iter(candidates)).schema
                if database is None:
                    return self.deny("view_scope_unresolved")
            reference = RelationReference(first, database)
            if source is None:
                allowed = self.policy.allows_resolved_relation(reference, self.default_schema)
            else:
                allowed = (fold(source), reference.key(case_sensitive=False)) in self.view_edges or (
                    fold(source) in self.cte_names and self.policy.allows_resolved_relation(reference, self.default_schema)
                )
                # Trigger NEW/OLD and indirect reads retain the database/table
                # supplied by SQLite. Only a verified non-executing DML plan
                # may use this direct grant, independent of its source label.
                if self.explain_dml:
                    allowed = allowed or self.policy.allows_resolved_relation(reference, self.default_schema)
            if not allowed and unscoped_count:
                # SQLite can drop the view source from an additional
                # COUNT READ of its base. All physical roots were checked
                # before activation; accept only a unique resolved base
                # already in the authorized view dependency graph.
                allowed = any(target == reference.key(case_sensitive=False)
                              for _, target in self.view_edges)
                allowed = allowed or any(target == reference.key(case_sensitive=False)
                                         for _, target in self.virtual_edges)
            allowed = allowed or (fold(source) if source is not None else None,
                                  reference.key(case_sensitive=False)) in self.virtual_edges
            allowed = allowed or reference.key(case_sensitive=False) in self.catalog_reads
            allowed = allowed or reference.key(case_sensitive=False) in self.module_reads
            allowed = allowed or fold(second or "") in self.module_columns.get(reference.key(case_sensitive=False), set())
            if not allowed and source is not None and self.request_plan_read(first, database, source):
                # An authorized view first reached from a trigger may need its
                # dependency edges. Abort preparation; never inspect SQL here.
                return self.deny("view_scope_unresolved")
            return sqlite3.SQLITE_OK if allowed else self.deny("table_access_denied")
        if action == sqlite3.SQLITE_FUNCTION:
            code = restricted_function_code({fold(second or "")})
            if code is not None:
                return self.deny(code)
            return sqlite3.SQLITE_OK
        if action in {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE}:
            if (self.explain_dml and source is not None and fold(source) not in self.prepared_sources
                    and self.request_plan_read(None, None, source)):
                return self.deny("view_scope_unresolved")
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_PRAGMA:
            # Callback parameters do not identify module provenance. These are
            # explicit operation-scoped abilities of verified FTS roots, after
            # all direct query/view references have been checked separately.
            if (second is None and database is not None
                    and (fold(first or ""), fold(database)) in self.module_pragmas):
                return sqlite3.SQLITE_OK
            return self.deny("server_state_denied")
        if self.explain_dml and action in {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}:
            # These are compilation events for a verified, non-executing DML
            # plan. Still authorize every target, including trigger targets.
            if first is None or database is None:
                return self.deny("table_access_denied")
            reference = RelationReference(first, database)
            allowed = self.policy.allows_resolved_relation(reference, self.default_schema)
            if (allowed and source is not None and fold(source) not in self.prepared_sources
                    and self.request_plan_read(None, None, source)):
                return self.deny("view_scope_unresolved")
            return sqlite3.SQLITE_OK if allowed else self.deny("table_access_denied")
        return self.deny("read_only_required")


def build_read_guard(connection: sqlite3.Connection, policy: ConnectionPolicy,
                     context: DialectContext, analysis, *, deadline: float | None = None,
                     plan_reads: frozenset[PlanRead] = frozenset(), catalog_limit: int = 2048) -> SQLiteReadGuard:
    """Resolve authorized view edges before activating the read callback.

    Catalog SQL is fixed trusted bootstrap, never an untrusted query or callback
    re-entry. Actual READ events must still match these edges and root grants.
    Views cannot turn their sources into directly authorized base tables.
    """
    from sql_safety_executor.core.analysis import analyze_sql, analyze_sqlite_trigger
    from sql_safety_executor.core.read_rules import restricted_function_code, _SQLITE_PRAGMA_OBJECTS

    guard = SQLiteReadGuard(policy, context.default_schema or "main", frozenset(fold(name.name) for name in analysis.names if name.role == "cte"))
    guard.explain_dml = (
        analysis.statement_kind == "explain"
        and analysis.explain_payload in {"insert", "update", "delete"}
        and not analysis.has_nested_write
    )
    guard.prepared_plan_reads = plan_reads
    cte_counts = Counter(fold(cte.name) for cte in analysis.ctes)
    candidate_ctes = {name for name, count in cte_counts.items() if count == 1}
    if not analysis.relations and not candidate_ctes and not analysis.virtual_relations:
        return guard
    schemas = [row[1] for row in connection.execute("PRAGMA database_list")]
    schemas.sort(key=lambda name: 0 if name == "temp" else 1 if name == "main" else 2)
    catalog: dict[RelationReference, tuple[str, str | None]] = {}
    observed: set[RelationReference] = set()

    def catalog_query(schema, name, kinds):
        if deadline is not None and time.monotonic() > deadline:
            raise DatabaseQueryError("query_timeout")
        if guard.catalog_lookups >= catalog_limit:
            raise DatabaseQueryError("view_scope_unresolved")
        guard.catalog_lookups += 1
        quoted = '"' + schema.replace('"', '""') + '"'
        # kinds is one of the two fixed internal tuples below, not SQL input.
        return list(connection.execute(
            f"SELECT name, type, sql FROM {quoted}.sqlite_master "
            f"WHERE name = ? COLLATE NOCASE AND type IN {kinds} LIMIT 2", (name,)
        ))

    def catalog_pragma(schema: str, operation: str, name: str, limit: int = 1):
        """Fixed catalog work on the owned connection, outside callbacks."""
        if operation not in {"table_list", "table_xinfo", "index_list"}:
            raise ValueError("Unsupported guard catalog PRAGMA")
        if deadline is not None and time.monotonic() >= deadline:
            raise DatabaseQueryError("query_timeout")
        if guard.catalog_lookups >= catalog_limit:
            raise DatabaseQueryError("view_scope_unresolved")
        guard.catalog_lookups += 1
        quoted_schema = '"' + schema.replace('"', '""') + '"'
        literal = "'" + name.replace("'", "''") + "'"
        cursor = connection.execute(f"PRAGMA {quoted_schema}.{operation}({literal})")
        try:
            rows = cursor.fetchmany(limit + 1)
        finally:
            cursor.close()
        if deadline is not None and time.monotonic() >= deadline:
            raise DatabaseQueryError("query_timeout")
        if len(rows) > limit:
            raise DatabaseQueryError("view_scope_unresolved")
        return rows

    def content_rowid_column(content: RelationReference, rowid: str) -> str:
        """Map implicit rowid spellings to SQLite's compile-time column name.

        A declared same-name column wins over an implicit alias. INTEGER PK
        aliases have no separate PK index; the historical inline DESC form
        does. WITHOUT ROWID and virtual/view objects gain no implicit alias.
        """
        if fold(rowid) not in {"rowid", "_rowid_", "oid"} or catalog[content][0] != "table":
            return rowid
        schema = content.schema or "main"
        tables = catalog_pragma(schema, "table_list", content.name)
        if not tables:
            raise DatabaseQueryError("view_scope_unresolved")
        actual_schema, actual_name, kind, _ncol, without_rowid, *_ = tables[0]
        if RelationReference(actual_name, actual_schema).key(case_sensitive=False) != content:
            raise DatabaseQueryError("view_scope_unresolved")
        if kind != "table" or without_rowid:
            return rowid
        columns = catalog_pragma(schema, "table_xinfo", content.name, 65536)
        if any(fold(column[1]) == fold(rowid) for column in columns):
            return rowid
        primary = [column for column in columns if column[5] > 0]
        if len(primary) == 1 and fold(primary[0][2]) == "integer":
            indexes = catalog_pragma(schema, "index_list", content.name, 65536)
            if not any(index[3] == "pk" for index in indexes):
                return primary[0][1]
        return "rowid"

    def lookup(key: RelationReference):
        if key.name in {"sqlite_master", "sqlite_schema"}:
            # These are real catalog aliases but do not list themselves in the
            # catalog. Preserve the requested schema, including empty-column
            # COUNT callbacks. Never infer arbitrary sqlite_* names as catalogs.
            catalog[key] = ("table", None)
            return catalog[key]
        if key.name in {"sqlite_temp_master", "sqlite_temp_schema"} and key.schema == "temp":
            catalog[key] = ("table", None)
            return catalog[key]
        if deadline is not None and time.monotonic() > deadline:
            raise DatabaseQueryError("query_timeout")
        if key not in observed:
            observed.add(key)
            schema = key.schema
            if schema is None:
                raise DatabaseQueryError("view_scope_unresolved")
            rows = catalog_query(schema, key.name, "('table','view')")
            if len(rows) > 1:
                raise DatabaseQueryError("view_scope_unresolved")
            if rows:
                name, kind, definition = rows[0]
                catalog[RelationReference(name, schema).key(case_sensitive=False)] = (kind, definition)
        return catalog.get(key)

    def resolve(reference: RelationReference, owner: str | None = None):
        search = [reference.schema] if reference.schema is not None else (
            [owner] if owner is not None and owner != "temp" else schemas
        )
        if reference.schema is None and fold(reference.name) in {"sqlite_master", "sqlite_schema"}:
            search = [owner or "main"]
        elif reference.schema is None and fold(reference.name) in {"sqlite_temp_master", "sqlite_temp_schema"}:
            search = ["temp"]
        for schema in search:
            key = RelationReference(reference.name, schema).key(case_sensitive=False)
            if lookup(key) is not None:
                guard.resolved_bindings.setdefault(key.name, set()).add(key)
                return key
        return None

    def catalog_aliases(target: RelationReference):
        if target.name not in {"sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema"}:
            return set()
        names = {"sqlite_master", "sqlite_schema"} if target.schema != "temp" else {
            "sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_temp_schema"}
        aliases = {RelationReference(name, target.schema) for name in names}
        for alias in aliases:
            guard.resolved_bindings.setdefault(alias.name, set()).add(alias)
        return aliases

    def record_virtuals(result, owner: RelationReference | None = None):
        for use in result.virtual_relations:
            if use.kind == "sqlite_named":
                target = resolve(RelationReference(use.name, use.schema), owner.schema if owner is not None else None)
                if target is None:
                    raise DatabaseQueryError("virtual_relation_unsupported")
                visit(target)
                if target not in guard.module_roots:
                    raise DatabaseQueryError("virtual_relation_unsupported")
                continue
            # SQLite's eponymous JSON modules emit main READs, even for a
            # qualified call or a temp/attached view. A syntactic qualifier is
            # not the module's physical binding (verified with native SQLite).
            schema = fold(guard.default_schema)
            if not any(fold(name) == schema for name in schemas) or use.name not in {"json_each", "json_tree"}:
                raise DatabaseQueryError("view_scope_unresolved")
            target = RelationReference(use.name, schema).key(case_sensitive=False)
            if use.schema is not None and not any(fold(name) == fold(use.schema) for name in schemas):
                raise DatabaseQueryError("relation_scope_unresolved")
            stored = resolve(RelationReference(use.name, use.schema), owner.schema if owner is not None else None)
            if stored is not None:
                # Resolve the actual object first. Only a verified, authorized
                # FTS5 root may use this spelling as a named table call; it
                # never inherits the eponymous JSON module's abilities.
                if fts5_definition(catalog[stored][1]) is None:
                    raise DatabaseQueryError("view_scope_unresolved")
                if owner is None and not policy.allows_resolved_relation(stored, guard.default_schema):
                    raise DatabaseQueryError("view_scope_unresolved")
                if owner is not None:
                    guard.view_edges.add((fold(use.source) if use.source is not None else owner.name, stored))
                visit(stored)
                continue
            if use.schema is not None and fold(use.schema) != schema:
                raise DatabaseQueryError("relation_scope_unresolved")
            if lookup(target) is not None:
                raise DatabaseQueryError("view_scope_unresolved")
            source = fold(use.source) if use.source is not None else owner.name if owner is not None else None
            guard.virtual_edges.add((source, target))
            guard.resolved_bindings.setdefault(target.name, set()).add(target)

    visited: set[RelationReference] = set()
    source_schemas: dict[str, str | None] = {}
    source_owners: dict[str, RelationReference | None] = {name: None for name in guard.cte_names}
    source_catalog: dict[str, list[tuple[RelationReference, str]]] = {}
    source_definitions: dict[RelationReference, str | None] = {}

    def source_objects(name):
        if name not in source_catalog:
            source_catalog[name] = []
            for schema in schemas:
                for actual_name, kind, definition in catalog_query(schema, name, "('view','trigger')"):
                    owner = RelationReference(actual_name, schema).key(case_sensitive=False)
                    source_catalog[name].append((owner, kind))
                    source_definitions[owner] = definition
        return source_catalog[name]

    def source_owner(name: str, owner: RelationReference):
        key = fold(name)
        if key in source_owners and source_owners[key] != owner:
            raise DatabaseQueryError("view_scope_unresolved")
        source_owners[key] = owner

    def visit(reference: RelationReference):
        if reference in visited or reference in guard.module_roots:
            return
        if catalog[reference][0] != "view":
            contract = fts5_definition(catalog[reference][1])
            if contract is None:
                return
            if len(guard.module_roots) >= 128:
                raise DatabaseQueryError("view_scope_unresolved")
            guard.module_roots.add(reference)
            guard.module_pragmas.add(("data_version", reference.schema or "main"))
            # Verify actual shadow identities of this known module, not a
            # blanket prefix grant. This is fixed catalog work outside callbacks.
            shadow_names = tuple(reference.name + suffix for suffix in ("_data", "_idx", "_content", "_docsize", "_config"))
            for name in shadow_names:
                # Statement PRAGMAs cannot be shadowed by pragma_* business
                # objects. Bind the actual module schema, not lookup order.
                rows = catalog_pragma(reference.schema or "main", "table_list", name)
                for actual_schema, actual_name, kind, *_ in rows:
                    target = RelationReference(actual_name, actual_schema).key(case_sensitive=False)
                    expected = RelationReference(name, reference.schema).key(case_sensitive=False)
                    if kind != "shadow" or target != expected:
                        raise DatabaseQueryError("virtual_relation_unsupported")
                    guard.module_reads.add(target)
                    guard.resolved_bindings.setdefault(target.name, set()).add(target)
            if contract.content is not None:
                content = resolve(RelationReference(contract.content, reference.schema))
                if content is None:
                    raise DatabaseQueryError("unknown_table")
                guard.module_columns.setdefault(content, set()).update(
                    {"", fold(content_rowid_column(content, contract.content_rowid)),
                     *(fold(column) for column in contract.columns)})
                visit(content)
            return
        visited.add(reference)
        if len(visited) > 128:
            raise DatabaseQueryError("view_scope_unresolved")
        # Callback source has no schema component. Ambiguous reachable source
        # spellings are unsupported rather than merged into a larger grant.
        previous = source_schemas.setdefault(reference.name, reference.schema)
        if previous != reference.schema:
            raise DatabaseQueryError("view_scope_unresolved")
        source_owner(reference.name, reference)
        if guard.explain_dml and source_objects(reference.name) != [(reference, "view")]:
            # DML plans can reach triggers as well as views. The callback source
            # lacks its schema/kind; never conflate matching source spellings.
            raise DatabaseQueryError("view_scope_unresolved")
        definition = catalog[reference][1]
        if not definition:
            raise DatabaseQueryError("view_scope_unresolved")
        result = analyze_sql(definition, context, view_definition=True)
        if not result.complete or result.has_nested_write:
            raise DatabaseQueryError("view_scope_unresolved")
        # FTS can retain an internal content statement prepared by trusted
        # execution. Compilation callbacks alone do not recheck its functions
        # on every evaluation. Check current, complete view facts before any
        # module work; do not apply the raw-query shape policy to stored views.
        code = restricted_function_code(result.functions)
        if code is not None:
            raise DatabaseQueryError(code)
        record_virtuals(result, reference)
        labels = [fold(cte.name) for cte in result.ctes]
        if len(labels) != len(set(labels)):
            raise DatabaseQueryError("view_scope_unresolved")
        for label in labels:
            source_owner(label, reference)
            candidate_ctes.add(label)
        for use in result.relation_uses:
            if fold(use.reference.name) in _SQLITE_PRAGMA_OBJECTS:
                raise DatabaseQueryError("server_state_denied")
            target = resolve(use.reference, reference.schema)
            if target is None:
                raise DatabaseQueryError("unknown_table")
            guard.view_edges.add((fold(use.source) if use.source is not None else reference.name, target))
            guard.view_edges.update((fold(use.source) if use.source is not None else reference.name, alias)
                                    for alias in catalog_aliases(target))
            if len(guard.view_edges) > 1024:
                raise DatabaseQueryError("view_scope_unresolved")
            visit(target)

    for reference in analysis.relations:
        target = resolve(reference)
        if target is not None:
            if not policy.allows_resolved_relation(target, guard.default_schema):
                raise DatabaseQueryError("table_access_denied")
            guard.catalog_reads.update(catalog_aliases(target))
            visit(target)
    record_virtuals(analysis)
    if guard.explain_dml:
        # Scope IDs are local to one analyzed trigger fragment. Keep the owner
        # and fragment in declaration identity; callback labels alone are not
        # a relation grant and must never become global ephemeral names.
        trigger_scopes: dict[tuple[RelationReference, int, int], set[str]] = {}
        fragment_labels: dict[tuple[RelationReference, int], set[str]] = {}
        trigger_labels: dict[str, set[RelationReference]] = {}
        sources = {source for _, _, source in plan_reads if source is not None}
        for source in sorted(sources):
            objects = source_objects(source)
            if objects or source in guard.cte_names:
                if len(objects) > 1:
                    raise DatabaseQueryError("view_scope_unresolved")
                if source in guard.cte_names:
                    if objects:
                        raise DatabaseQueryError("view_scope_unresolved")
                    guard.plan_count_sources.add(source)
                    guard.prepared_sources.add(source)
                if len(objects) == 1:
                    owner, kind = objects[0]
                    if kind == "view" and (owner in visited or policy.allows_resolved_relation(owner, guard.default_schema)):
                        lookup(owner)
                        visit(owner)
                        guard.prepared_sources.add(source)
                    elif kind == "trigger":
                        source_owner(source, owner)
                        definition = source_definitions[owner]
                        results = analyze_sqlite_trigger(definition, context) if definition else None
                        if results is None:
                            raise DatabaseQueryError("view_scope_unresolved")
                        for fragment, result in enumerate(results):
                            code = restricted_function_code(result.functions)
                            if code is not None:
                                raise DatabaseQueryError(code)
                            for cte in result.ctes:
                                label = fold(cte.name)
                                trigger_scopes.setdefault((owner, fragment, cte.scope), set()).add(label)
                                fragment_labels.setdefault((owner, fragment), set()).add(label)
                                trigger_labels.setdefault(label, set()).add(owner)
                            for reference in result.relations:
                                if fold(reference.name) in _SQLITE_PRAGMA_OBJECTS:
                                    raise DatabaseQueryError("server_state_denied")
                                target = resolve(reference, owner.schema)
                                if target is None:
                                    raise DatabaseQueryError("unknown_table")
                                if not policy.allows_resolved_relation(target, guard.default_schema):
                                    raise DatabaseQueryError("table_access_denied")
                                visit(target)
                            record_virtuals(result, owner)
                        # SQLite can report a view's extra empty-column READ
                        # under its trigger's source. Accept view edges only
                        # after every explicit trigger-body/WHEN dependency was
                        # checked; a separate direct base count cannot borrow it.
                        guard.plan_count_sources.add(owner.name)
                        guard.prepared_sources.add(source)
        # Fully check every fragment's physical dependencies before considering
        # its CTE counts. Shared labels keep separate owner/fragment identities;
        # all of their physical dependencies have been checked independently.
        # Real source objects or outer/view owners must not share those labels.
        unambiguous_labels = {
            label for label, owners in trigger_labels.items()
            if not source_objects(label)
            and (label not in source_owners or source_owners[label] in owners)
        }
        guard.prepared_sources.update(unambiguous_labels)
        for (owner, fragment, _), labels in trigger_scopes.items():
            local_sources = {owner.name} | (fragment_labels[owner, fragment] & unambiguous_labels)
            for label in labels & unambiguous_labels:
                if not any(lookup(RelationReference(label, schema).key(case_sensitive=False)) is not None
                           for schema in schemas):
                    guard.trigger_cte_reads.update((label, source) for source in local_sources)
        guard.prepared_sources.update(reference.name for reference in visited)
        for source in sources - guard.prepared_sources:
            if source in source_owners and not source_objects(source):
                guard.prepared_sources.add(source)
            else:
                raise DatabaseQueryError("view_scope_unresolved")
        for name, database, source in sorted(plan_reads, key=repr):
            if name is None or database is not None or (name, source) in guard.trigger_cte_reads:
                continue
            # Include unauthorized shadows. A single authorized candidate does
            # not prove SQLite read it; a verified local CTE is handled above.
            candidates = {key for schema in schemas
                          if lookup(key := RelationReference(name, schema).key(case_sensitive=False)) is not None}
            virtual_candidates = {target for label, target in guard.virtual_edges
                                  if label == source and target.name == name}
            if virtual_candidates:
                if candidates or len(virtual_candidates) != 1:
                    raise DatabaseQueryError("view_scope_unresolved")
                guard.resolved_bindings[name] = virtual_candidates
                continue
            if len(candidates) != 1:
                raise DatabaseQueryError("view_scope_unresolved")
            guard.resolved_bindings[name] = candidates
    # Callback READ labels have no scope/schema for these CTE events. Never
    # infer an ephemeral identity if a real main/temp/attached object could share
    # it. Catalog work stays outside the callback and within the existing budget.
    guard.ephemeral_ctes = frozenset(
        name for name in sorted(candidate_ctes)
        if not any(lookup(RelationReference(name, schema).key(case_sensitive=False))
                   is not None for schema in schemas)
    )
    return guard
