"""Managed-plan statement classification, independent of read authorization.

The original SQL is retained. A successful classification is not proof that
the database accepts the syntax, resolves the intended objects or approves a
write. Parameter, Skill, approval, token and transaction checks stay separate.
"""
from __future__ import annotations

from itertools import product
from typing import Literal

from sqlglot import exp
from sqlglot.errors import ParseError, TokenError
from sqlglot.tokenizer_core import TokenType

from .analysis import _tokens, has_unsupported_sql_comments
from .decisions import PolicyDecision
from sql_safety_executor.database.semantics import DialectContext
from sql_safety_executor.database.transport import named_parameters

ManagedPlanParser = Literal["sqlglot", "sqlparse"]
_DML = (exp.Insert, exp.Update, exp.Delete)
_NESTED_STATEMENTS = (*_DML, exp.Create, exp.Drop, exp.Alter, exp.Merge, exp.Command)
_STATEMENT_MESSAGE = "Managed mutation plans require one direct INSERT, UPDATE, or DELETE statement"


def managed_plan_contexts(databases=None) -> tuple[DialectContext, ...]:
    """Startup candidates only; execution must use its actual target context."""
    supported = set(databases or ("sqlite", "mysql"))
    contexts = [DialectContext("sqlite")] if "sqlite" in supported else []
    if "mysql" in supported:
        names = ("ANSI_QUOTES", "NO_BACKSLASH_ESCAPES", "PIPES_AS_CONCAT", "HIGH_NOT_PRECEDENCE")
        contexts.extend(DialectContext("mysql", frozenset(name for name, on in zip(names, bits) if on))
                        for bits in product((False, True), repeat=4))
    return tuple(contexts)


def check_managed_sql(sql: str, context: DialectContext, parser: ManagedPlanParser = "sqlglot",
                      parameter_names: frozenset[str] | None = None) -> PolicyDecision:
    """Classify one managed DML using the selected, never-fallback parser."""
    if parser not in {"sqlglot", "sqlparse"}:
        raise ValueError("Unsupported managed mutation plan parser")
    if not isinstance(context, DialectContext):
        return PolicyDecision.deny("session_semantics_unavailable", "Managed mutation target SQL semantics are unavailable.")
    if parser == "sqlparse":
        # Temporary explicit rollback implementation. Keep its original
        # classification, including its intentionally dialect-neutral scope.
        import sqlparse
        statements = [item for item in sqlparse.parse(sql) if str(item).strip(" \t\r\n;")]
        if len(statements) != 1 or statements[0].get_type().upper() not in {"INSERT", "UPDATE", "DELETE"}:
            return PolicyDecision.deny("managed_plan_statement_invalid", _STATEMENT_MESSAGE)
        if parameter_names is not None:
            try:
                if named_parameters(sql, context) != parameter_names:
                    return PolicyDecision.deny("managed_plan_bindings_invalid", "Managed mutation plan parameters must exactly match SQL named binds")
            except (ParseError, TokenError, ValueError, TypeError, AttributeError, KeyError, IndexError, RecursionError):
                return PolicyDecision.deny("managed_plan_sql_parse_failed", "Managed mutation plan bindings could not be analyzed for this dialect and session.")
        return PolicyDecision.allow()
    try:
        # Reuse the existing project dialect/session lexer and its public AST
        # parser. No new SQLGlot private parser override or read policy applies.
        dialect, tokens = _tokens(sql, context)
        if has_unsupported_sql_comments(sql, tokens, context, dialect):
            return PolicyDecision.deny("managed_plan_comment_unsupported", "Managed mutation comments must be ordinary dialect comments or supported plan hints; executable, state-changing and ambiguous forms are unsupported.")
        tokens = [token for token in tokens if token.token_type != TokenType.HINT]
        trees = [tree for tree in dialect.parser().parse(tokens, sql)
                 if tree is not None and not isinstance(tree, exp.Semicolon)]
        if len(trees) != 1 or not isinstance(trees[0], _DML):
            return PolicyDecision.deny("managed_plan_statement_invalid", _STATEMENT_MESSAGE)
        tree = trees[0]
        if any(isinstance(child, _NESTED_STATEMENTS) for child in tree.walk() if child is not tree):
            return PolicyDecision.deny("managed_plan_statement_invalid", _STATEMENT_MESSAGE)
        # SQLite/MySQL can normalize bare REPLACE into Insert. Check the
        # original main verb, excluding root CTE declaration-name positions
        # and parenthesized bodies; INSERT OR REPLACE remains INSERT.
        with_ = tree.args.get("with_")
        aliases = {cte.args["alias"].this.meta.get("start") for cte in with_.expressions} if with_ else set()
        depth = 0
        verb = None
        for token in tokens:
            if token.token_type == TokenType.L_PAREN:
                depth += 1
            elif token.token_type == TokenType.R_PAREN:
                depth -= 1
            elif depth == 0 and token.start not in aliases and token.token_type in {
                    TokenType.INSERT, TokenType.UPDATE, TokenType.DELETE, TokenType.REPLACE}:
                verb = token.text.upper()
                break
        if verb != type(tree).__name__.upper():
            return PolicyDecision.deny("managed_plan_statement_invalid", _STATEMENT_MESSAGE)
        if any(not isinstance(node.this, str) or not node.this for node in tree.find_all(exp.Placeholder)):
            return PolicyDecision.deny("parameter_binding_unsupported", "Managed mutation plans require named parameters, not positional placeholders.")
        if parameter_names is not None and named_parameters(sql, context, tokens=tokens) != parameter_names:
            return PolicyDecision.deny("managed_plan_bindings_invalid", "Managed mutation plan parameters must exactly match SQL named binds")
    except (ParseError, TokenError, ValueError, TypeError, AttributeError, KeyError, IndexError, RecursionError):
        return PolicyDecision.deny("managed_plan_sql_parse_failed", "Managed mutation plan SQL could not be analyzed for this dialect and session.")
    return PolicyDecision.allow()
