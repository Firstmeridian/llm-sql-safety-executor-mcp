"""Experimental AST projection. Never imported by the production package."""
from dataclasses import asdict, dataclass, field
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import build_scope

ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")

@dataclass
class Analysis:
    statement_kind: str
    physical_tables: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    ctes: list[str] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    sqlglot_scope_tables: list[str] = field(default_factory=list)

def analyze(sql, dialect, *, cte_exact=False):
    trees = sqlglot.parse(sql, read=dialect)
    if len(trees) != 1 or trees[0] is None:
        return Analysis("unknown", unsupported=["statement_count"])
    tree = trees[0]
    result = Analysis(type(tree).__name__)
    if isinstance(tree, exp.Command):
        result.unsupported.append("opaque_command")
        return result
    fold = (lambda name: name) if cte_exact else (lambda name: name.translate(ASCII_LOWER))
    physical, functions, ctes, parameters = set(), set(), set(), set()

    def table_name(node):
        return ".".join(part.name for part in node.parts)

    def walk(node, visible):
        with_clause = node.args.get("with_")
        own = set(visible)
        if with_clause:
            definitions = with_clause.expressions
            names = {fold(c.alias_or_name) for c in definitions}
            ctes.update(c.alias_or_name for c in definitions)
            for cte in definitions:
                body_scope = own | names if dialect == "sqlite" else set(own)
                if with_clause.args.get("recursive"):
                    body_scope.add(fold(cte.alias_or_name))
                walk(cte.this, body_scope)
                own.add(fold(cte.alias_or_name))
        if isinstance(node, exp.Table):
            if isinstance(node.this, exp.Identifier):
                if node.db or node.catalog or fold(node.name) not in own:
                    physical.add(table_name(node))
            else:
                result.unsupported.append("virtual_relation")
        if isinstance(node, exp.In) and node.args.get("field") is not None:
            # SQLite bare IN RHS is a relation represented as a Column, so a
            # generic Table traversal and SQLGlot Scope omit it entirely.
            rhs = node.args["field"]
            if isinstance(rhs, exp.Column):
                if rhs.table or fold(rhs.name) not in own:
                    physical.add(".".join(part.name for part in rhs.parts))
            else:
                result.unsupported.append("membership_virtual_relation")
        if isinstance(node, exp.Func):
            name = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            functions.add(name.translate(ASCII_LOWER))
        if isinstance(node, exp.Placeholder):
            parameters.add(node.name)
        for key, value in node.args.items():
            if key == "with_":
                continue
            for child in value if isinstance(value, list) else [value]:
                if isinstance(child, exp.Expression):
                    walk(child, own)

    walk(tree, set())
    try:
        scope = build_scope(tree)
        if scope:
            for child in scope.traverse():
                for _, target in child.selected_sources.values():
                    if isinstance(target, exp.Table) and isinstance(target.this, exp.Identifier):
                        result.sqlglot_scope_tables.append(table_name(target))
    except Exception as error:
        result.unsupported.append("scope_" + type(error).__name__)
    result.physical_tables = sorted(physical)
    result.functions = sorted(functions)
    result.ctes = sorted(ctes)
    result.parameters = sorted(parameters)
    result.unsupported = sorted(set(result.unsupported))
    result.sqlglot_scope_tables = sorted(set(result.sqlglot_scope_tables))
    return result

def projection(sql, dialect, **kwargs):
    return asdict(analyze(sql, dialect, **kwargs))
