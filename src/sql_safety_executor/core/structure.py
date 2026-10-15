"""Bounded lexical CTE structure shared by classification and relation analysis.

This is not a dialect-validating AST. Original token spelling and body text are
preserved; keyword labels and sqlparse's optional Identifier grouping do not
decide whether a declaration is a name or where its query body ends.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import sqlparse
from sqlparse import tokens as T
from sqlparse.sql import Function, Identifier, IdentifierList, Parenthesis, Token, TokenList, Where

_ASCII_UPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
sql_tokens = T


def sql_token_upper(token: Token) -> str:
    """Compare SQL vocabulary from its original, ASCII-folded spelling."""
    return token.value.translate(_ASCII_UPPER)


def decode_identifier(value: str) -> str:
    """Decode one identifier quote layer, keeping all significant contents."""
    if len(value) >= 2:
        for opening, closing in (("`", "`"), ('"', '"'), ("[", "]")):
            if value[0] == opening and value[-1] == closing:
                return value[1:-1].replace(closing * 2, closing)
    return value


def significant_sql_tokens(token_list: TokenList) -> list[Any]:
    # sqlparse can close a WHERE group before a keyword-like RHS name (for
    # example IN unıon). Keep WHERE at its surrounding block so its operand
    # cannot be lost across that optional grouping boundary.
    return [part for t in token_list.tokens if not t.is_whitespace and t.ttype not in T.Comment
            for part in (significant_sql_tokens(t) if isinstance(t, Where) else [t])]


def _name(token: Token) -> str:
    value = token.value
    if (len(value) >= 2 and (value[0], value[-1]) in
            {('"', '"'), ("`", "`"), ("[", "]")}):
        name = decode_identifier(value)
    elif token.ttype in T.Name or value.isidentifier():
        name = value
    else:
        raise ValueError("Unsupported CTE identifier")
    if not name:
        raise ValueError("Empty CTE identifier")
    return name


def _word(token: Token, value: str) -> bool:
    return token.ttype in T.Keyword and sql_token_upper(token) == value


def _punctuation(token: Token, value: str) -> bool:
    return token.ttype is T.Punctuation and token.value == value


@dataclass(frozen=True)
class SQLFragment:
    tokens: tuple[Token, ...]

    @property
    def sql(self) -> str:
        return "".join(token.value for token in self.tokens)

    def parse(self) -> sqlparse.sql.Statement:
        statements = [s for s in sqlparse.parse(self.sql) if str(s).strip(" \t\r\n;")]
        if len(statements) != 1:
            raise ValueError("Expected one CTE query fragment")
        return statements[0]


@dataclass(frozen=True)
class CTEDefinition:
    name: str
    columns: tuple[str, ...]
    body: SQLFragment
    # Header leaves only: never include AS, materialization or query-body tokens.
    declaration_token_ids: frozenset[int]
    materialization: str | None


@dataclass(frozen=True)
class WithClause:
    recursive: bool
    definitions: tuple[CTEDefinition, ...]
    query: SQLFragment


def parse_with_clause(token_list: TokenList) -> WithClause | None:
    """Read one query block's WITH header using balanced original leaves.

    Parenthesized query blocks and non-executing EXPLAIN prefixes are supported.
    Other nested expressions are handled by callers visiting their own blocks.
    An encountered but incomplete/unsupported WITH raises instead of inventing
    a SELECT classification or silently discarding a relation dependency.
    """
    first = next((t for t in token_list.flatten() if not t.is_whitespace and t.ttype not in T.Comment), None)
    if first is None or not (_word(first, "WITH") or _word(first, "EXPLAIN") or _punctuation(first, "(")):
        return None
    leaves = tuple(token_list.flatten())
    positions = [i for i, t in enumerate(leaves) if not t.is_whitespace and t.ttype not in T.Comment]
    tokens = [leaves[i] for i in positions]
    if not tokens:
        return None
    # Remove only enclosing punctuation belonging to this whole query block.
    start, end = 0, len(tokens)
    while start < end and _punctuation(tokens[start], "("):
        depth, close = 0, None
        for i in range(start, end):
            if _punctuation(tokens[i], "("):
                depth += 1
            elif _punctuation(tokens[i], ")"):
                depth -= 1
                if depth == 0:
                    close = i
                    break
        if close != end - 1:
            return None
        start, end = start + 1, end - 1
    if start >= end:
        return None
    index = start
    if _word(tokens[index], "EXPLAIN"):
        # Do not treat a later WITH identifier inside an explained SELECT as a
        # declaration. Stop at the first actual DML command or relation group.
        index += 1
        while index < end and not _word(tokens[index], "WITH"):
            if tokens[index].ttype in T.Keyword.DML or _punctuation(tokens[index], "("):
                return None
            index += 1
        if index == end:
            return None
    if not _word(tokens[index], "WITH"):
        return None
    index += 1
    recursive = index < end and _word(tokens[index], "RECURSIVE")
    if recursive:
        index += 1

    def parenthesis(open_index: int) -> int:
        if open_index >= end or not _punctuation(tokens[open_index], "("):
            raise ValueError("Expected CTE parentheses")
        depth = 0
        for j in range(open_index, end):
            if _punctuation(tokens[j], "("):
                depth += 1
            elif _punctuation(tokens[j], ")"):
                depth -= 1
                if depth == 0:
                    return j
        raise ValueError("Unclosed CTE parentheses")

    definitions = []
    while index < end:
        header_start = index
        name = _name(tokens[index])
        index += 1
        columns: tuple[str, ...] = ()
        if index < end and _punctuation(tokens[index], "("):
            close = parenthesis(index)
            column_tokens = tokens[index + 1:close]
            if not column_tokens or len(column_tokens) % 2 == 0:
                raise ValueError("Invalid CTE column list")
            columns = tuple(_name(t) for t in column_tokens[::2])
            if any(not _punctuation(t, ",") for t in column_tokens[1::2]):
                raise ValueError("Invalid CTE column separator")
            index = close + 1
        if index >= end or not _word(tokens[index], "AS"):
            raise ValueError("Missing CTE AS")
        header_ids = frozenset(id(t) for t in tokens[header_start:index])
        index += 1
        materialization = None
        if index < end and _word(tokens[index], "NOT"):
            materialization = "NOT MATERIALIZED"
            index += 1
            if index >= end or not _word(tokens[index], "MATERIALIZED"):
                raise ValueError("Unsupported CTE materialization hint")
            index += 1
        elif index < end and _word(tokens[index], "MATERIALIZED"):
            materialization = "MATERIALIZED"
            index += 1
        close = parenthesis(index)
        body = SQLFragment(leaves[positions[index] + 1:positions[close]])
        body_first = next((t for t in body.tokens if not t.is_whitespace and t.ttype not in T.Comment), None)
        if body_first is None:
            raise ValueError("Empty CTE query body")
        if not (body_first.ttype in T.Keyword.DML or _word(body_first, "WITH") or _word(body_first, "VALUES")):
            raise ValueError("Unsupported CTE query body")
        definitions.append(CTEDefinition(name, columns, body, header_ids, materialization))
        index = close + 1
        if index < end and _punctuation(tokens[index], ","):
            index += 1
            continue
        break
    if not definitions or index >= end:
        raise ValueError("WITH has no main statement")
    query = SQLFragment(leaves[positions[index]:positions[end - 1] + 1])
    if not (tokens[index].ttype in T.Keyword.DML or _word(tokens[index], "WITH")):
        raise ValueError("Unsupported WITH main statement")
    return WithClause(bool(recursive), tuple(definitions), query)


def cte_declaration_token_ids(token_list: TokenList) -> set[int]:
    """Collect declaration-only leaves across original nested parse groups."""
    excluded: set[int] = set()
    clause = parse_with_clause(token_list)
    if clause is not None:
        for definition in clause.definitions:
            excluded.update(definition.declaration_token_ids)
    for child in token_list.tokens:
        if isinstance(child, TokenList):
            excluded.update(cte_declaration_token_ids(child))
    return excluded


def membership_relation_targets(tokens: list[Any]) -> list[Any]:
    """SQLite IN's bare RHS is a relation, even outside WHERE/FROM clauses.

    Parenthesized value lists/subqueries are traversed separately. A function
    here names a virtual table, not a CTE; its argument subqueries still share
    the current CTE scope. No SQL is rewritten or executed during validation.
    """
    targets = []
    for index, token in enumerate(tokens):
        if token.ttype not in sql_tokens.Keyword or sql_token_upper(token) not in {"IN", "NOT IN"}:
            continue
        if index + 1 >= len(tokens):
            raise ValueError("IN has no right-hand operand")
        target = tokens[index + 1]
        if isinstance(target, Parenthesis):
            continue
        if isinstance(target, IdentifierList):
            target = next(iter(target.get_identifiers()))
        targets.append(target)
    return targets


def relation_targets(tokens: list[Any], *, preserve_qualification: bool = False) -> list[Any]:
    """Collect relation targets in this query block, including loose commas.

    sqlparse does not consistently group single-quoted qualified names or
    comma-separated parenthesized targets. Track the FROM clause explicitly
    instead of assuming every next target is one Identifier/List token.
    """
    targets: list[Any] = []
    in_from = False
    expect_target = False
    for index, token in enumerate(tokens):
        command = sql_token_upper(token)
        # A target immediately after FROM/JOIN/comma takes precedence over a
        # contextual keyword spelling. Otherwise window/offset/lock vanish
        # before authorization. Unicode lexer labels do not establish syntax.
        clause_boundary = isinstance(token, Where) or (
            token.ttype in sql_tokens.Keyword and command in {
                "WHERE", "GROUP BY", "ORDER BY", "HAVING", "LIMIT", "OFFSET",
                "UNION", "UNION ALL", "INTERSECT", "EXCEPT", "WINDOW", "FOR", "LOCK",
            }
        )
        if not expect_target and clause_boundary:
            in_from = False
            expect_target = False
        if token.ttype in sql_tokens.Keyword and (
            command in {"FROM", "JOIN", "STRAIGHT_JOIN"} or command.endswith(" JOIN")
        ):
            in_from = True
            expect_target = True
            continue
        if in_from and token.value == ",":
            expect_target = True
            continue
        if expect_target:
            items = list(token.get_identifiers()) if isinstance(token, IdentifierList) else [token]
            if index + 2 < len(tokens) and tokens[index + 1].value == ".":
                # Only the last item can be the schema prefix when sqlparse
                # grouped a preceding comma-separated table into this token.
                if preserve_qualification:
                    items.append(tokens[index + 2])
                else:
                    items[-1] = tokens[index + 2]
            targets.extend(items)
            expect_target = False
        elif in_from and isinstance(token, IdentifierList):
            # sqlparse may group an ON expression and the following table as
            # one IdentifierList: ON a.id=b.id, other_table. Only the first
            # member belongs to the expression; later members are relations.
            items = list(token.get_identifiers())[1:]
            if items and index + 2 < len(tokens) and tokens[index + 1].value == ".":
                if preserve_qualification:
                    items.append(tokens[index + 2])
                else:
                    items[-1] = tokens[index + 2]
            targets.extend(items)
    if expect_target and tokens:
        # Preserve an incomplete FROM/JOIN/comma as an unresolvable target so
        # strict authorization extraction fails closed instead of finding none.
        targets.append(tokens[-1])
    targets.extend(membership_relation_targets(tokens))
    return targets


def relation_name_token_ids(token_list: TokenList) -> set[int]:
    """Names at relation targets, never whole groups or query arguments.

    Authorization uses the same selector. Contextual REPLACE in comma/JOIN/IN
    targets is a name; actual body/main write commands stay visible.
    """
    def names(target: Token) -> set[int]:
        if isinstance(target, IdentifierList):
            return {i for item in target.get_identifiers() for i in names(item)}
        if isinstance(target, (Identifier, Function)):
            parts = significant_sql_tokens(target)
            if not parts:
                return set()
            result = names(parts[0])
            if len(parts) >= 3 and parts[1].value == ".":
                result.update(names(parts[2]))
            return result
        if isinstance(target, TokenList):
            return set()
        return {id(target)}

    result = {i for target in relation_targets(significant_sql_tokens(token_list)) for i in names(target)}
    for child in token_list.tokens:
        if isinstance(child, TokenList):
            result.update(relation_name_token_ids(child))
    return result

