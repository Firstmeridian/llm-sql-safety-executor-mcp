"""Small, catalog-backed contracts for supported SQLite virtual tables."""
from dataclasses import dataclass

from .errors import DatabaseQueryError
from .identifiers import ascii_identifier_lower as fold


@dataclass(frozen=True)
class FTS5Definition:
    columns: tuple[str, ...]
    content: str | None
    content_rowid: str


def fts5_definition(definition: str | None) -> FTS5Definition | None:
    """Inspect an engine-stored declaration, never execute or rewrite it.

    None denotes an ordinary table/view or a different module. Other modules
    never inherit FTS capabilities; their existing read checks still apply.
    The existing dialect tokenizer decodes quoted names and option values.
    """
    if not definition:
        return None
    from sql_safety_executor.core.analysis import _SQLite
    from sqlglot.tokenizer_core import TokenType

    tokens = _SQLite().tokenize(definition)
    if len(tokens) < 3 or [fold(token.text) for token in tokens[:3]] != ["create", "virtual", "table"]:
        return None
    if len(tokens) > 2048:
        raise DatabaseQueryError("virtual_relation_unsupported")
    using = next((i for i, token in enumerate(tokens) if token.token_type == TokenType.USING), None)
    if using is None or using + 3 >= len(tokens):
        raise DatabaseQueryError("virtual_relation_unsupported")
    if fold(tokens[using + 1].text) != "fts5":
        return None
    if tokens[using + 2].token_type != TokenType.L_PAREN:
        raise DatabaseQueryError("virtual_relation_unsupported")
    groups, current = [], []
    for token in tokens[using + 3:]:
        if token.token_type == TokenType.R_PAREN:
            if current:
                groups.append(current)
            break
        if token.token_type == TokenType.COMMA:
            groups.append(current)
            current = []
        else:
            current.append(token)
    else:
        raise DatabaseQueryError("virtual_relation_unsupported")
    columns, options = [], {}
    for group in groups:
        if len(group) == 3 and group[1].token_type == TokenType.EQ:
            key = fold(group[0].text)
            if key in options:
                raise DatabaseQueryError("virtual_relation_unsupported")
            options[key] = group[2].text
        elif len(group) == 1 or len(group) == 2 and fold(group[1].text) == "unindexed":
            columns.append(group[0].text)
        else:
            raise DatabaseQueryError("virtual_relation_unsupported")
    if not columns:
        raise DatabaseQueryError("virtual_relation_unsupported")
    return FTS5Definition(tuple(columns), options.get("content") or None, options.get("content_rowid", "rowid"))
