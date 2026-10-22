"""Dialect-aware, bounded SQLGlot analysis. Original SQL is never regenerated."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import re
from typing import Literal

import sqlglot
from sqlglot import exp
from sqlglot.dialects.mysql import MySQL
from sqlglot.dialects.sqlite import SQLite
from sqlglot.errors import ParseError, TokenError
from sqlglot.tokenizer_core import Token, TokenType
from .read_rules import _ACCOUNT_FUNCTIONS, _LOCK_FUNCTIONS, _EXPENSIVE_FUNCTIONS, _SQLITE_PRAGMA_OBJECTS

from sql_safety_executor.database.identifiers import ascii_identifier_lower
from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.database.semantics import DialectContext, NameRole

_ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_WRITES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter)


def _reserved_parsers():
    # Project-reserved calls are rejected regardless of arity; do not let a
    # SQLGlot built-in's arity normalization hide their original call identity.
    def parser(name):
        return lambda args: exp.Anonymous(this=name, expressions=args)
    return {name.upper(): parser(name) for name in _ACCOUNT_FUNCTIONS | _LOCK_FUNCTIONS | _EXPENSIVE_FUNCTIONS | {"load_file"}}


@dataclass(frozen=True)
class NameOccurrence:
    name: str
    role: NameRole
    raw: str
    quote: str | None
    start: int | None
    end: int | None
    scope: int


@dataclass(frozen=True)
class QueryScope:
    identity: int
    parent: int | None
    visible_ctes: tuple[str, ...]


@dataclass(frozen=True)
class CTEDeclaration:
    name: str
    columns: tuple[str, ...]
    scope: int
    order: int
    recursive: bool
    materialized: bool | None


@dataclass(frozen=True)
class RelationUse:
    reference: RelationReference
    scope: int
    source: str | None  # Innermost CTE body; None means the query/view body.


@dataclass(frozen=True)
class VirtualRelationUse:
    """Known builtin relation call, distinct from physical table grants."""
    name: str
    schema: str | None
    scope: int
    source: str | None
    kind: Literal["builtin", "sqlite_named", "sqlite_json"] = "builtin"


@dataclass(frozen=True)
class SQLAnalysis:
    status: Literal["complete", "partial", "failed"]
    statement_kind: str
    relations: tuple[RelationReference, ...] = ()
    functions: frozenset[str] = frozenset()
    names: tuple[NameOccurrence, ...] = ()
    parameters: frozenset[str] = frozenset()
    unsupported: tuple[str, ...] = ()
    has_union: bool = False
    has_derived_relation: bool = False
    has_nested_write: bool = False
    has_file_output: bool = False
    has_system_variable: bool = False
    context_key: tuple = ()
    source_sql: str = field(default="", repr=False)
    parameter_positions: tuple[int, ...] = ()
    scopes: tuple[QueryScope, ...] = ()
    ctes: tuple[CTEDeclaration, ...] = ()
    relation_uses: tuple[RelationUse, ...] = ()
    explain_payload: str | None = None
    has_locking_read: bool = False
    has_session_assignment: bool = False
    virtual_relations: tuple[VirtualRelationUse, ...] = ()

    @property
    def complete(self) -> bool:
        return self.status == "complete"


@lru_cache(maxsize=16)
def _mysql_dialect(ansi_quotes: bool, no_backslash: bool, pipes_concat: bool = False, high_not: bool = False):
    # These classes are cached interpretation settings, never policy results.
    class SessionMySQL(MySQL):
        DPIPE_IS_STRING_CONCAT = pipes_concat
        class Tokenizer(MySQL.Tokenizer):
            QUOTES = ["'"] if ansi_quotes else ["'", '"']
            IDENTIFIERS = ["`", '"'] if ansi_quotes else ["`"]
            STRING_ESCAPES = ["'", '"'] if no_backslash else ["'", '"', "\\"]
            COMMANDS = MySQL.Tokenizer.COMMANDS - {TokenType.REPLACE, TokenType.SHOW}

        class Parser(MySQL.Parser):
            FUNCTIONS = {**MySQL.Parser.FUNCTIONS, **_reserved_parsers()}
            # SQLGlot puts both spellings in NOT's unary dispatch. MySQL's !
            # always binds tightly; NOT does so only under HIGH_NOT_PRECEDENCE.
            # Retain infix NOT IN/BETWEEN/LIKE parsing and original token text.
            UNARY_PARSERS = {**MySQL.Parser.UNARY_PARSERS, TokenType.NOT:
                lambda self: self.expression(exp.Not(this=(
                    self._parse_unary() if high_not or self._prev.text == "!"
                    else self._parse_equality()
                )))
            }
            def _statement_modifiers(self, allowed):
                while self._curr and self._curr.token_type != TokenType.IDENTIFIER and self._curr.text.translate(_ASCII_UPPER) in allowed:
                    self._advance()

            def _parse_update(self):
                self._statement_modifiers({"LOW_PRIORITY", "IGNORE"})
                return super()._parse_update()

            def _parse_insert(self):
                self._statement_modifiers({"LOW_PRIORITY", "HIGH_PRIORITY", "DELAYED", "IGNORE"})
                return super()._parse_insert()

            def _parse_delete(self):
                self._statement_modifiers({"LOW_PRIORITY", "QUICK", "IGNORE"})
                return super()._parse_delete()
    return SessionMySQL()


class _SQLite(SQLite):
    class Tokenizer(SQLite.Tokenizer):
        # SQLite has only these three bare current-time keywords. Standard
        # CURRENT_USER/LOCALTIME spellings are ordinary business identifiers.
        KEYWORDS = {**SQLite.Tokenizer.KEYWORDS, **{
            name: TokenType.VAR for name, kind in SQLite.Tokenizer.KEYWORDS.items()
            if kind in SQLite.Parser.NO_PAREN_FUNCTIONS
            and name not in {"CURRENT_DATE", "CURRENT_TIME", "CURRENT_TIMESTAMP"}
        }}
        # Keep EXPLAIN's payload as real tokens, not one opaque string.
        COMMANDS = SQLite.Tokenizer.COMMANDS - {TokenType.COMMAND, TokenType.REPLACE, TokenType.SHOW}

    class Parser(SQLite.Parser):
        FUNCTIONS = {**SQLite.Parser.FUNCTIONS, **_reserved_parsers()}
        # Dispatch at a real statement slot, including the main statement after
        # WITH. Names and replace() calls never go through this dispatch.
        STATEMENT_PARSERS = {**SQLite.Parser.STATEMENT_PARSERS,
                             TokenType.REPLACE: lambda self: self._parse_replace()}
        ID_VAR_TOKENS = SQLite.Parser.ID_VAR_TOKENS | {TokenType.LIKE, TokenType.RLIKE}
        ALIAS_TOKENS = SQLite.Parser.ALIAS_TOKENS | {TokenType.LIKE, TokenType.RLIKE}
        TABLE_ALIAS_TOKENS = SQLite.Parser.TABLE_ALIAS_TOKENS | {TokenType.LIKE, TokenType.RLIKE, TokenType.WINDOW, TokenType.LOCK, TokenType.FOR}

        # SQLite permits a postfix/arithmetic continuation after a completed
        # range predicate. Upstream consumes these tiers only before it, so
        # resume them locally without moving COLLATE onto an IN operand.
        _PREDICATE_TAIL_PRECEDENCE = {
            **{token: 1 for token in SQLite.Parser.BITWISE},
            **{token: 2 for token in SQLite.Parser.TERM if token != TokenType.COLLATE},
            **{token: 3 for token in SQLite.Parser.FACTOR},
            **{token: 4 for token in SQLite.Parser.CONCAT_OPERATORS},
        }

        def _parse_range(self, this: exp.Expr | None = None) -> exp.Expr | None:
            this = super()._parse_range(this)
            while this is not None:
                index = self._index
                this = self._parse_predicate_tail(this)
                if self._index == index:
                    break
                this = super()._parse_range(this)
            return this

        def _parse_predicate_tail(self, this: exp.Expr, minimum: int = 1) -> exp.Expr:
            while True:
                token = self._curr.token_type
                shift = token in {TokenType.LT, TokenType.GT} and self._next.token_type == token
                precedence = 1 if shift else self._PREDICATE_TAIL_PRECEDENCE.get(token, 0)
                if token != TokenType.COLLATE and precedence < minimum:
                    return this
                # Make the completed predicate atomic, including normalized
                # NOT IN / ISNULL nodes whose printed form has lower precedence.
                if isinstance(this, (exp.Predicate, exp.Not)):
                    this = self.expression(exp.Paren(this=this))
                if self._match(TokenType.COLLATE):
                    this = self.expression(exp.Collate(this=this, expression=self._parse_unary()))
                    self._normalize_collate(this)
                    continue
                self._advance(2 if shift else 1)
                right = self._parse_concat_operand()
                if right is None:
                    self.raise_error("Expected SQLite predicate continuation operand")
                    return this
                right = self._parse_predicate_tail(right, precedence + 1)
                if shift:
                    kind = exp.BitwiseLeftShift if token == TokenType.LT else exp.BitwiseRightShift
                    this = self.expression(kind(this=this, expression=right))
                elif token in self.CONCAT_OPERATORS:
                    this = self.CONCAT_OPERATORS[token](self, this, right)
                else:
                    operators = self.FACTOR if precedence == 3 else self.TERM if precedence == 2 else self.BITWISE
                    this = self.expression(operators[token](this=this, expression=right))
                    if isinstance(this, exp.Div):
                        this.set("typed", self.dialect.TYPED_DIVISION)
                        this.set("safe", self.dialect.SAFE_DIVISION)

        def _parse_is(self, this: exp.Expr | None) -> exp.Expr | None:
            # SQLGlot's NULL/placeholder shortcut leaves a following COLLATE
            # unconsumed. SQLite's IS right operand is an expression: parse its
            # precedence normally, preserving COLLATE on that operand rather
            # than moving it onto the whole predicate. Execute the original SQL.
            right_token = self._next if self._curr.token_type == TokenType.NOT else self._curr
            if right_token.token_type != TokenType.NULL and right_token.token_type not in self.PLACEHOLDER_PARSERS:
                return super()._parse_is(this)
            negate = self._match(TokenType.NOT)
            right = self._parse_bitwise()
            if right is None:
                self.raise_error("Expected SQLite IS right operand")
            if negate and isinstance(right, exp.Null) and not self.dialect.NORMALIZE_NOT_NULL:
                this = self.expression(exp.Is(this=this, expression=right, negate=True))
            else:
                this = self.expression(exp.Is(this=this, expression=right))
                this = self.expression(exp.Not(this=this)) if negate else this
            return self._parse_column_ops(this)

        def _parse_escape(self, this: exp.Expr | None) -> exp.Expr | None:
            if not self._match(TokenType.ESCAPE):
                return this
            # A string/NULL shortcut also omits postfix COLLATE here. Consume
            # the escape operand at its proper precedence, retaining all uses.
            right = self._parse_bitwise()
            if right is None:
                self.raise_error("Expected SQLite ESCAPE operand")
            return self.expression(exp.Escape(this=this, expression=right))

        def trigger_when_begin(self, tokens: list[Token], sql: str) -> int:
            """Consume the condition as an expression, then require its marker.

            A keyword token can be a column/function/CTE inside WHEN. Let the
            dialect parser consume those roles before inspecting the next token.
            The caller separately analyzes every body fragment; consuming the
            remainder here never exempts its dependencies or functions.
            """
            boundary: int | None = None

            def condition(parser):
                nonlocal boundary
                expression = parser._parse_disjunction()
                if expression is None or parser._curr.token_type != TokenType.BEGIN:
                    parser.raise_error("Expected trigger body BEGIN after WHEN expression")
                boundary = parser._curr.start
                parser._advance(parser._tokens_size - parser._index)
                return expression

            self._parse(condition, tokens, sql)
            if boundary is None:
                raise ValueError("Missing trigger WHEN expression or body")
            return boundary

        def _parse_replace(self):
            result = self._parse_insert()
            if isinstance(result, exp.Insert):
                result.set("alternative", "REPLACE")
            return result

        def _parse_update(self):
            if self._match(TokenType.OR):
                choice = self._curr
                if (choice is None or choice.token_type in {TokenType.IDENTIFIER, TokenType.STRING}
                        or choice.text.translate(_ASCII_UPPER) not in {"ROLLBACK", "ABORT", "FAIL", "IGNORE", "REPLACE"}):
                    self.raise_error("Expected SQLite conflict resolution")
                self._advance()
            return super()._parse_update()

        def _parse_table_alias(self, alias_tokens=None):
            if self._can_parse_named_window():
                return None
            return super()._parse_table_alias(alias_tokens)

        def _parse_in(self, this, alias=False):
            if self._curr and self._curr.token_type != TokenType.IDENTIFIER and self._curr.text.isidentifier():
                self._curr.token_type = TokenType.VAR
            if self._curr.token_type not in {TokenType.L_PAREN, TokenType.L_BRACKET}:
                # SQLite's table-form IN has the same name/argument semantics
                # as FROM. Scalar function aliases and arity do not apply.
                return self.expression(exp.In(this=this, field=self._parse_table_parts()))
            return super()._parse_in(this, alias=alias)

        def _parse_table_part(self, schema=False):
            if not schema:
                function = self._parse_function(anonymous=True, optional_parens=False)
                if function is not None:
                    function.meta["sqlite_relation_call"] = True
                    return function
            return super()._parse_table_part(schema=schema)

        def _parse_table_parts(self, *args, **kwargs):
            if self._prev.token_type == TokenType.INDEXED_BY and self._curr.text.isidentifier() and self._curr.token_type != TokenType.IDENTIFIER:
                self._curr.token_type = TokenType.VAR
            return super()._parse_table_parts(*args, **kwargs)

        def _parse_cte(self):
            # In a declaration-name slot a keyword-like spelling is a name,
            # not a speculative OFFSET clause or a second WITH query.
            if self._curr and self._curr.token_type != TokenType.IDENTIFIER and self._curr.text.isidentifier():
                self._curr.token_type = TokenType.VAR
            return super()._parse_cte()

        def _parse_table(self, *args, **kwargs):
            # Preserve real subquery dispatch. WITH is also a legal SQLite
            # business name: only its declaration opener belongs to a query.
            start = self._index + 1
            if start < self._tokens_size and self._tokens[start].token_type == TokenType.RECURSIVE:
                start += 1
            with_query = (self._curr.token_type == TokenType.WITH and start + 1 < self._tokens_size
                          and self._tokens[start + 1].token_type in {TokenType.ALIAS, TokenType.L_PAREN})
            if (self._curr and self._curr.token_type not in {
                    TokenType.IDENTIFIER, TokenType.TABLE, TokenType.SELECT, TokenType.VALUES}
                    and not with_query and self._curr.text.isidentifier()):
                self._curr.token_type = TokenType.VAR
            return super()._parse_table(*args, **kwargs)


def _tokens(sql: str, context: DialectContext):
    dialect = (_mysql_dialect("ANSI_QUOTES" in context.sql_modes, "NO_BACKSLASH_ESCAPES" in context.sql_modes, "PIPES_AS_CONCAT" in context.sql_modes, "HIGH_NOT_PRECEDENCE" in context.sql_modes)
               if context.dialect == "mysql" else _SQLite())
    tokens = dialect.tokenize(sql)
    # SQLGlot classifies keywords with Unicode upper(). Restore non-ASCII
    # business spellings before parsing, keeping offsets and original text.
    for token in tokens:
        if token.text.isidentifier() and token.text.translate(_ASCII_UPPER) != token.text.upper():
            if token.token_type not in {TokenType.STRING, TokenType.IDENTIFIER}:
                token.token_type = TokenType.VAR
    if context.dialect == "sqlite":
        for index, token in enumerate(tokens):
            if token.token_type == TokenType.STRING and index and tokens[index - 1].token_type in {TokenType.FROM, TokenType.JOIN, TokenType.IN, TokenType.DOT}:
                # Project legacy quoted targets structurally so policy can
                # report PRAGMA access or unsupported quoting, never grant it.
                token.token_type = TokenType.IDENTIFIER
    if tokens and tokens[0].text.translate(_ASCII_UPPER) in {"DESC", "DESCRIBE"}:
        tokens[0].token_type = TokenType.DESCRIBE
    if context.dialect == "mysql":
        for index, token in enumerate(tokens):
            if token.token_type == TokenType.REPLACE and index + 1 < len(tokens) and tokens[index + 1].token_type != TokenType.L_PAREN:
                previous = tokens[index - 1] if index else None
                if previous is None or previous.token_type in {TokenType.L_PAREN, TokenType.DESCRIBE}:
                    token.token_type = TokenType.INSERT
    return dialect, tokens


_MYSQL_PLAN_HINTS = frozenset({
    "BKA", "NO_BKA", "BNL", "NO_BNL", "DERIVED_CONDITION_PUSHDOWN", "NO_DERIVED_CONDITION_PUSHDOWN",
    "GROUP_INDEX", "NO_GROUP_INDEX", "HASH_JOIN", "NO_HASH_JOIN", "INDEX", "NO_INDEX",
    "INDEX_MERGE", "NO_INDEX_MERGE", "JOIN_FIXED_ORDER", "JOIN_INDEX", "NO_JOIN_INDEX",
    "JOIN_ORDER", "JOIN_PREFIX", "JOIN_SUFFIX", "MERGE", "NO_MERGE", "MRR", "NO_MRR",
    "NO_ICP", "NO_RANGE_OPTIMIZATION", "ORDER_INDEX", "NO_ORDER_INDEX", "QB_NAME",
    "SEMIJOIN", "NO_SEMIJOIN", "SKIP_SCAN", "NO_SKIP_SCAN", "SUBQUERY",
})


def _mysql_plan_hint_supported(body: str, dialect) -> bool:
    """Recognize only complete named plan hints with flat name arguments.

    No SET_VAR, resource assignment, timeout override, unknown names, nested
    expressions or parser fallback-to-string. This is a supported subset, not
    proof that the server applies a hint or accepts all its arguments.
    """
    tokens = dialect.tokenize(body)
    end = 0
    for token in tokens:
        if body[end:token.start].strip() or token.comments:
            return False
        end = token.end + 1
    if body[end:].strip():
        return False
    index = 0
    while index < len(tokens):
        name = tokens[index]
        if name.token_type in {TokenType.STRING, TokenType.IDENTIFIER} or name.text.translate(_ASCII_UPPER) not in _MYSQL_PLAN_HINTS:
            return False
        index += 1
        if index >= len(tokens) or tokens[index].token_type != TokenType.L_PAREN:
            return False
        index += 1
        arguments = []
        while index < len(tokens) and tokens[index].token_type != TokenType.R_PAREN:
            token = tokens[index]
            if not (token.token_type == TokenType.IDENTIFIER or
                    token.token_type not in {TokenType.STRING, TokenType.NATIONAL_STRING} and token.text.isidentifier() or
                    token.token_type == TokenType.COMMA or token.token_type == TokenType.PARAMETER and token.text == "@"):
                return False
            if token.token_type == TokenType.COMMA and (not arguments or arguments[-1].token_type in {TokenType.COMMA, TokenType.PARAMETER}):
                return False
            arguments.append(token)
            index += 1
        if index == len(tokens) or arguments and arguments[-1].token_type in {TokenType.COMMA, TokenType.PARAMETER}:
            return False
        index += 1
    return True


def has_unsupported_sql_comments(sql: str, tokens, context: DialectContext, dialect) -> bool:
    """Check every raw trivia region/hint, never strings or quoted names."""
    previous_end = 0
    gaps = []
    for token in tokens:
        gaps.append(sql[previous_end:token.start])
        if token.token_type == TokenType.HINT:
            gaps.append(sql[token.start:token.end + 1])
        previous_end = token.end + 1
    gaps.append(sql[previous_end:])
    if context.dialect == "mysql" and any(a.text == b.text == "-" and a.end + 1 == b.start and (b.end + 1 == len(sql) or not sql[b.end + 1].isspace()) for a, b in zip(tokens, tokens[1:])):
        return True
    for gap in gaps:
        index = 0
        while index < len(gap):
            if gap[index].isspace():
                index += 1
            elif gap.startswith("/*", index):
                end = gap.find("*/", index + 2)
                if end < 0:
                    return True
                if context.dialect == "mysql":
                    if gap.startswith(("/*!", "/*M!"), index):
                        return True
                    if gap.startswith("/*+", index) and not _mysql_plan_hint_supported(gap[index + 3:end], dialect):
                        return True
                index = end + 2
            elif gap.startswith("--", index):
                if context.dialect == "mysql" and (index + 2 == len(gap) or not gap[index + 2].isspace()):
                    return True
                end = gap.find("\n", index + 2)
                index = len(gap) if end < 0 else end + 1
            elif context.dialect == "mysql" and gap[index] == "#":
                end = gap.find("\n", index + 1)
                index = len(gap) if end < 0 else end + 1
            else:
                return True
    return False


def analyze_sql(sql: str, context: DialectContext, *, view_definition: bool = False) -> SQLAnalysis:
    """Complete means complete for this project's supported analysis contract.

    It does not certify server syntax, catalog existence or view internals.
    Unsupported nodes remain explicit even when SQLGlot accepted the input.
    """
    if not sql.strip():
        return SQLAnalysis("failed", "empty", unsupported=("empty_sql",), context_key=context.fingerprint)
    prefix = []
    try:
        dialect, raw_tokens = _tokens(sql, context)
        # HINT is comment trivia, including after a final terminator. Retain
        # raw tokens for complete dialect checks; statement shape uses only
        # executable tokens and their unchanged original positions.
        tokens = [token for token in raw_tokens if token.token_type != TokenType.HINT]
        prefix = [token.text.translate(_ASCII_UPPER) for token in tokens[:4]]
        if any(a.token_type == TokenType.L_BRACE and b.text.translate(_ASCII_UPPER) == "OJ" for a, b in zip(tokens, tokens[1:])):
            return SQLAnalysis("partial", "unknown", unsupported=("odbc_relation",), context_key=context.fingerprint)
        if any(token.token_type == TokenType.SEMICOLON for token in tokens[:-1]):
            return SQLAnalysis("failed", "unknown", unsupported=("multiple_statements",), context_key=context.fingerprint)
        if any(a.token_type == TokenType.COMMA and b.token_type == TokenType.R_PAREN for a, b in zip(tokens, tokens[1:])):
            return SQLAnalysis("failed", "with" if prefix[:1] == ["WITH"] else "unknown", unsupported=("sql_parse_failed",), context_key=context.fingerprint)
        if has_unsupported_sql_comments(sql, raw_tokens, context, dialect):
            return SQLAnalysis("complete", "unsafe_comment", context_key=context.fingerprint)
        # Hints have been validated from all original spans. Omit them only
        # from analysis so hint-relative AST offsets cannot impersonate names,
        # functions or dependencies in the actual SQL. Execute original SQL.
        if prefix[:1] == ["SHOW"]:
            return SQLAnalysis("complete", "show", context_key=context.fingerprint)
        if (prefix[:1] in (["SELECT"], ["WITH"], ["EXPLAIN"], ["DESCRIBE"], ["DESC"])
                and any(token.token_type == TokenType.PLACEHOLDER and token.text == "?" for token in tokens)):
            return SQLAnalysis("partial", "unsupported_binding", context_key=context.fingerprint)
        if (context.dialect == "mysql" and prefix[:1] in (["DO"], ["HANDLER"])
                and tokens[0].token_type not in {TokenType.IDENTIFIER, TokenType.STRING}):
            return SQLAnalysis("complete", "nonread_command", context_key=context.fingerprint)
        if context.dialect == "mysql" and any(
                a.token_type == TokenType.INTO and b.token_type == TokenType.PARAMETER
                for a, b in zip(tokens, tokens[1:])):
            # Includes MySQL's trailing INTO form, which upstream cannot parse.
            # This is a rejection fact, never an executable incomplete plan.
            return SQLAnalysis("complete", "select", has_session_assignment=True, context_key=context.fingerprint)
        if any(a.token_type == TokenType.INTO and b.token_type not in {TokenType.STRING, TokenType.IDENTIFIER} and b.text.translate(_ASCII_UPPER) in {"OUTFILE", "DUMPFILE"} for a, b in zip(tokens, tokens[1:])):
            return SQLAnalysis("complete", "select", has_file_output=True, context_key=context.fingerprint)
        explained = bool(prefix and prefix[0] in {"EXPLAIN", "DESCRIBE", "DESC"})
        if explained and any(a.text.translate(_ASCII_UPPER) == "FOR" and b.text.translate(_ASCII_UPPER) == "CONNECTION" for a, b in zip(tokens, tokens[1:])):
            return SQLAnalysis("complete", "session_inspection", context_key=context.fingerprint)
        if explained and ("ANALYZE" in prefix or prefix[1:2] == ["("]):
            return SQLAnalysis("complete", "executing_explain", context_key=context.fingerprint)
        if explained and context.dialect == "sqlite":
            # SQLite EXPLAIN is otherwise an opaque SQLGlot Command. Parse its
            # non-executing payload using the same tokens and original offsets.
            if prefix[:3] == ["EXPLAIN", "QUERY", "PLAN"]:
                tokens = tokens[3:]
            elif prefix[0] == "EXPLAIN":
                tokens = tokens[1:]
        # A trailing comment after a terminator becomes a Semicolon node in
        # SQLGlot. All raw trivia was checked above; this is no executable
        # statement. Original-token and tree checks still reject real SQL.
        trees = [tree for tree in dialect.parser().parse(tokens, sql)
                 if tree is not None and not isinstance(tree, exp.Semicolon)]
        if len(trees) != 1:
            return SQLAnalysis("failed", "unknown", unsupported=("multiple_statements",), context_key=context.fingerprint)
        tree = trees[0]
    except (ParseError, TokenError, ValueError, IndexError, RecursionError):
        return SQLAnalysis("failed", "with" if prefix[:1] == ["WITH"] else "unknown", unsupported=("sql_parse_failed",), context_key=context.fingerprint)

    if view_definition:
        if not isinstance(tree, exp.Create) or tree.args.get("kind") != "VIEW" or tree.expression is None:
            return SQLAnalysis("partial", "unknown", unsupported=("view_definition",), context_key=context.fingerprint)
        tree = tree.expression
    if isinstance(tree, exp.Describe):
        explained = True
        tree = tree.this
    if explained and not isinstance(tree, (exp.Select, exp.SetOperation, exp.Table, *_WRITES)):
        return SQLAnalysis("partial", "explain", unsupported=("explain_payload",), context_key=context.fingerprint)
    kind = "explain" if explained else "select" if isinstance(tree, (exp.Select, exp.SetOperation)) else type(tree).__name__.lower()
    unsupported: set[str] = set()
    relations: set[RelationReference] = set()
    functions: set[str] = set()
    parameters: set[str] = set()
    names: list[NameOccurrence] = []
    scopes = 0
    scope_records: list[QueryScope] = []
    cte_records: list[CTEDeclaration] = []
    relation_uses: list[RelationUse] = []
    virtual_relations: list[VirtualRelationUse] = []
    token_at = {token.start: token for token in tokens}
    derived = nested_write = file_output = system_variable = False
    locking_read = session_assignment = False

    def occurrence(identifier, role: NameRole, scope: int):
        if not isinstance(identifier, exp.Identifier):
            return
        start, end = identifier.meta.get("start"), identifier.meta.get("end")
        raw = sql[start:end + 1] if isinstance(start, int) and isinstance(end, int) else identifier.name
        quote = raw[0] if identifier.args.get("quoted") and raw else None
        names.append(NameOccurrence(identifier.name, role, raw, quote, start, end, scope))
        if not context.valid_name(identifier.name, role):
            unsupported.add("invalid_identifier")
        if role in {"schema", "relation", "cte"} and quote == "'":
            unsupported.add("relation_quoting_unsupported")
        if role in {"schema", "relation", "cte"} and quote == '"' and context.dialect == "mysql" and "ANSI_QUOTES" not in context.sql_modes:
            unsupported.add("relation_quoting_unsupported")

    def reference(node, visible, scope, source, *, membership=False):
        if membership and isinstance(node, exp.Dot) and isinstance(node.this, exp.Identifier) and isinstance(node.expression, exp.Func):
            function = node.expression
            name = function.name if isinstance(function, exp.Anonymous) else function.sql_name()
            occurrence(node.this, "schema", scope)
            if context.dialect == "sqlite" and ascii_identifier_lower(name) in {"json_each", "json_tree"}:
                virtual_relations.append(VirtualRelationUse(ascii_identifier_lower(name), node.this.name, scope, source, "sqlite_json"))
                return
            ref = RelationReference(name, node.this.name)
            relations.add(ref)
            relation_uses.append(RelationUse(ref, scope, source))
            if context.dialect == "sqlite" and ascii_identifier_lower(name) not in _SQLITE_PRAGMA_OBJECTS:
                virtual_relations.append(VirtualRelationUse(name, node.this.name, scope, source, "sqlite_named"))
            return
        if isinstance(node, exp.Column):  # SQLite's table-form IN operand
            parts = node.parts
        elif isinstance(node, exp.Table) and isinstance(node.this, exp.Identifier):
            parts = node.parts
        else:
            # Record a callable virtual relation; do not pretend it has no
            # dependency merely because it is not an exp.Table identifier.
            fn = node.this if isinstance(node, exp.Table) else node
            if isinstance(fn, exp.Func):
                name = fn.name if isinstance(fn, exp.Anonymous) else fn.sql_name()
                schema = node.db if isinstance(node, exp.Table) and node.db else None
                if context.dialect == "sqlite" and fn.meta.get("sqlite_relation_call"):
                    identifier = fn.this if isinstance(fn.this, exp.Identifier) else exp.Identifier(this=name)
                    if not identifier.meta:
                        identifier.meta.update(fn.meta)
                    occurrence(identifier, "relation", scope)
                    if schema:
                        occurrence(node.args.get("db"), "schema", scope)
                if isinstance(node, exp.Table) and node.catalog:
                    unsupported.add("relation_components")
                    return
                builtin = (context.dialect == "sqlite" and ascii_identifier_lower(name) in {"json_each", "json_tree"}
                           or context.dialect == "mysql" and isinstance(fn, exp.JSONTable))
                if builtin:
                    if schema:
                        occurrence(node.args.get("db"), "schema", scope)
                    virtual_relations.append(VirtualRelationUse(
                        ascii_identifier_lower(name), schema, scope, source,
                        "sqlite_json" if context.dialect == "sqlite" else "builtin"))
                    return
                ref = RelationReference(name, schema)
                relations.add(ref)
                relation_uses.append(RelationUse(ref, scope, source))
                if context.dialect == "sqlite" and ascii_identifier_lower(name) not in _SQLITE_PRAGMA_OBJECTS:
                    # A named SQLite virtual call has an ordinary root identity.
                    # Actual module support is verified from the execution
                    # connection's catalog before it gains internal abilities.
                    virtual_relations.append(VirtualRelationUse(name, schema, scope, source, "sqlite_named"))
                    return
                if membership and context.dialect == "sqlite":
                    return
            unsupported.add("virtual_relation")
            return
        if not 1 <= len(parts) <= 2 or any(not isinstance(p, exp.Identifier) for p in parts):
            unsupported.add("relation_components")
            return
        name = parts[-1].name
        schema = parts[0].name if len(parts) == 2 else None
        is_cte = schema is None and context.cte_key(name) in visible
        occurrence(parts[-1], "cte" if is_cte else "relation", scope)
        if schema is not None:
            occurrence(parts[0], "schema", scope)
        if not is_cte:
            ref = RelationReference(name, schema)
            relations.add(ref)
            relation_uses.append(RelationUse(ref, scope, source))

    def walk(node, visible: frozenset[str], *, root=False, scope=0, source=None):
        nonlocal scopes, derived, nested_write, file_output, system_variable, locking_read, session_assignment
        new_scope = root or isinstance(node, (exp.Select, exp.SetOperation))
        parent_scope = scope or None
        if new_scope:
            scopes += 1
            scope = scopes
        own = set(visible)
        with_clause = node.args.get("with_")
        if with_clause:
            definitions = with_clause.expressions
            # SQLite binds every declaration in this WITH block inside each
            # body, including implicit recursion. MySQL binds earlier CTEs
            # and only the explicit RECURSIVE declaration itself.
            if context.dialect == "sqlite":
                own.update(context.cte_key(cte.alias) for cte in definitions)
            for order, cte in enumerate(definitions):
                alias = cte.args.get("alias")
                if not isinstance(alias, exp.TableAlias) or not isinstance(alias.this, exp.Identifier):
                    unsupported.add("cte_declaration")
                    continue
                occurrence(alias.this, "cte", scope)
                for column in alias.args.get("columns") or ():
                    occurrence(column, "column_alias", scope)
                cte_records.append(CTEDeclaration(alias.name, tuple(column.name for column in alias.args.get("columns") or ()), scope, order, bool(with_clause.args.get("recursive")), cte.args.get("materialized")))
                if not isinstance(cte.this, (exp.Select, exp.SetOperation, *_WRITES)):
                    unsupported.add("cte_body")
                body_scope = set(own)
                if with_clause.args.get("recursive"):
                    body_scope.add(context.cte_key(alias.name))
                walk(cte.this, frozenset(body_scope), scope=scope, source=alias.name)
                own.add(context.cte_key(alias.name))
        if new_scope:
            scope_records.append(QueryScope(scope, parent_scope, tuple(sorted(own))))
        if isinstance(node, _WRITES) and not root:
            nested_write = True
        if isinstance(node, _WRITES):
            using = node.args.get("using") or ()
            if not isinstance(using, (list, tuple)):
                using = (using,)
            if isinstance(node.this, (exp.Subquery, exp.Paren)) or any(isinstance(value, (exp.Subquery, exp.Paren)) for value in using):
                derived = True
        if isinstance(node, exp.Command):
            unsupported.add("opaque_command")
        if isinstance(node, exp.Table):
            if isinstance(node.parent, exp.Table) and node.parent.args.get("indexed") is node:
                occurrence(node.this, "index", scope)
            elif not (isinstance(node.parent, exp.In) and node.parent.args.get("field") is node):
                reference(node, own, scope, source)
            if isinstance(node.parent, (exp.Exists, exp.SetOperation)):
                unsupported.add("table_query_expression")
        if isinstance(node, exp.In) and node.args.get("field") is not None:
            reference(node.args["field"], own, scope, source, membership=True)
        if isinstance(node, exp.Func) and not node.meta.get("sqlite_relation_call"):
            position = node.meta.get("start")
            original = token_at.get(position) if isinstance(position, int) else None
            name = original.text if original is not None else node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            functions.add(ascii_identifier_lower(name))
        if isinstance(node, exp.Placeholder):
            parameters.add(node.name)
        if isinstance(node, exp.SessionParameter):
            system_variable = True
        if isinstance(node, exp.Parameter) and isinstance(node.this, exp.Parameter):
            system_variable = True
        if isinstance(node, exp.Into):
            if isinstance(node.this, exp.Table) and isinstance(node.this.this, exp.Parameter):
                session_assignment = True
            else:
                file_output = True
        if isinstance(node, exp.PropertyEQ) and isinstance(node.this, exp.Parameter):
            session_assignment = True
        if isinstance(node, exp.Lock):
            locking_read = True
        if isinstance(node, exp.From) or isinstance(node, exp.Join):
            if isinstance(node.this, (exp.Subquery, exp.Paren)):
                derived = True
        alias = node.args.get("alias")
        if isinstance(alias, exp.TableAlias):
            occurrence(alias.this, "table_alias", scope)
        elif isinstance(node, exp.Alias):
            occurrence(alias, "column_alias", scope)
        for key, value in node.args.items():
            if key == "with_":
                continue
            for child in value if isinstance(value, list) else [value]:
                if isinstance(child, exp.Expr):
                    walk(child, frozenset(own), scope=scope, source=source)

    try:
        walk(tree, frozenset(), root=True)
    except (TypeError, ValueError, AttributeError, RecursionError):
        unsupported.add("analysis_structure")
    if not explained and kind not in {"select", "show"} and isinstance(tree, exp.Table):
        unsupported.add("statement_kind")
    return SQLAnalysis(
        "partial" if unsupported else "complete", kind,
        tuple(sorted(relations, key=lambda r: (r.schema or "", r.name))),
        frozenset(functions), tuple(names), frozenset(parameters), tuple(sorted(unsupported)),
        any(isinstance(node, exp.Union) for node in tree.walk()), derived,
        nested_write, file_output, system_variable, context.fingerprint,
        sql, tuple(a.start for a, b in zip(tokens, tokens[1:]) if a.token_type == TokenType.COLON and a.end + 1 == b.start and bool(re.fullmatch(r"\w+", b.text))),
        tuple(sorted(scope_records, key=lambda item: item.identity)), tuple(sorted(cte_records, key=lambda item: (item.scope, item.order))),
        tuple(relation_uses),
        type(tree).__name__.lower() if explained else None,
        locking_read, session_assignment,
        tuple(virtual_relations),
    )


def analyze_sqlite_trigger(definition: str, context: DialectContext) -> tuple[SQLAnalysis, ...] | None:
    """Analyze catalog trigger dependencies needed for ambiguous count events.

    This only separates SQLite's WHEN and BEGIN...END regions. SQLGlot still
    analyzes each expression/statement; no trigger SQL is executed or rewritten.
    Unsupported definitions fail closed rather than imply no dependencies.
    """
    if context.dialect != "sqlite":
        return None
    try:
        _, tokens = _tokens(definition, context)
        if not tokens or tokens[0].token_type != TokenType.CREATE:
            return None
        on = next(i for i, token in enumerate(tokens) if token.token_type == TokenType.ON)
        after_table = on + 2
        if tokens[after_table].token_type == TokenType.DOT:
            after_table += 2
        if tokens[after_table].token_type == TokenType.FOR:
            row_clause = tokens[after_table:after_table + 3]
            if (len(row_clause) != 3
                    or any(token.token_type in {TokenType.IDENTIFIER, TokenType.STRING} for token in row_clause)
                    or [token.text.translate(_ASCII_UPPER) for token in row_clause] != ["FOR", "EACH", "ROW"]):
                return None
            after_table += 3
        when = tokens[after_table] if tokens[after_table].token_type == TokenType.WHEN else None
        if when is not None:
            # The first body semicolon bounds this small parser entry point.
            # Quoted names/strings contain no SEMICOLON token. The full body
            # remains subject to the original fragment analysis below.
            end = next(i for i in range(after_table + 1, len(tokens)) if tokens[i].token_type == TokenType.SEMICOLON)
            start = _SQLite.Parser(dialect=_SQLite()).trigger_when_begin(tokens[after_table + 1:end], definition)
            begin = next(i for i in range(after_table + 1, end) if tokens[i].start == start)
        elif tokens[after_table].token_type == TokenType.BEGIN:
            begin = after_table
        else:
            return None
        last = len(tokens) - 1
        while tokens[last].token_type == TokenType.SEMICOLON:
            last -= 1
        if tokens[last].token_type != TokenType.END or last <= begin:
            return None
        fragments = []
        if when is not None:
            fragments.append("SELECT (" + definition[when.end + 1:tokens[begin].start] + ")")
        start = tokens[begin].end + 1
        for token in tokens[begin + 1:last]:
            if token.token_type == TokenType.SEMICOLON:
                fragment = definition[start:token.start].strip()
                if fragment:
                    fragments.append(fragment)
                start = token.end + 1
        if definition[start:tokens[last].start].strip():
            return None  # SQLite requires the final statement's semicolon.
        results = tuple(analyze_sql(fragment, context) for fragment in fragments)
        if not results or any(not result.complete or result.has_nested_write
                              or result.statement_kind not in {"select", "insert", "update", "delete"}
                              for result in results):
            return None
        return results
    except (ParseError, TokenError, ValueError, IndexError, StopIteration, RecursionError):
        return None
