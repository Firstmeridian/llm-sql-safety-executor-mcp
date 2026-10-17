"""Protect literal colons from SQLAlchemy's text binder, preserving DB SQL."""
import re

from sqlalchemy import text


def statement_text(sql, context, analysis=None):
    """Only actual named parameters become SQLAlchemy bind parameters.

    SQLAlchemy unescapes the added protection before driver execution. A colon
    in a quoted name, literal or comment is data, including an original
    backslash before that colon. This is transport compilation, not SQL AST
    generation, transpilation, or a database-side query rewrite.
    """
    if analysis is not None and analysis.source_sql == sql and analysis.context_key == context.fingerprint:
        positions = frozenset(analysis.parameter_positions)
    else:
        from sql_safety_executor.core.analysis import _tokens
        from sqlglot.tokenizer_core import TokenType
        _, tokens = _tokens(sql, context)
        positions = frozenset(a.start for a, b in zip(tokens, tokens[1:])
                              if a.token_type == TokenType.COLON and a.end + 1 == b.start
                              and re.fullmatch(r"\w+", b.text))
    protected = "".join("\\:" if char == ":" and index not in positions else char
                        for index, char in enumerate(sql))
    return text(protected)
