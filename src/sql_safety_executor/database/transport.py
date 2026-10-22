"""Protect literal colons from SQLAlchemy's text binder, preserving DB SQL."""
import re

from sqlalchemy import text


def statement_text(sql, context, analysis=None, *, tokens=None):
    """Only actual named parameters become SQLAlchemy bind parameters.

    SQLAlchemy unescapes the added protection before driver execution. A colon
    in a quoted name, literal or comment is data, including an original
    backslash before that colon. This is transport compilation, not SQL AST
    generation, transpilation, or a database-side query rewrite.
    """
    # SQLAlchemy cannot discover a named text bind without a colon. Catalog
    # templates commonly have none; avoid tokenizing or rebuilding their text.
    # This is only transport preparation, never SQL policy authorization.
    if ":" not in sql:
        return text(sql)
    if analysis is not None and analysis.source_sql == sql and analysis.context_key == context.fingerprint:
        positions = frozenset(analysis.parameter_positions)
    else:
        from sql_safety_executor.core.analysis import _tokens
        from sqlglot.tokenizer_core import TokenType
        if tokens is None:
            _, tokens = _tokens(sql, context)
        positions = frozenset(a.start for a, b in zip(tokens, tokens[1:])
                              if a.token_type == TokenType.COLON and a.end + 1 == b.start
                              and re.fullmatch(r"\w+", b.text))
    protected = "".join("\\:" if char == ":" and index not in positions else char
                        for index, char in enumerate(sql))
    return text(protected)


def named_parameters(sql, context, *, tokens=None):
    """Return exactly the actual named binds used by execution transport.

    No SQL is executed or normalized. The context must be a startup candidate
    or the actual execution target, never a guessed global dialect. Optional
    lexer tokens only avoid duplicate pure work within a classification.
    """
    return frozenset(statement_text(sql, context, tokens=tokens).compile().params)
