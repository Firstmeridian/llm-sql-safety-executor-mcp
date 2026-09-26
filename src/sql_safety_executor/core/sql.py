"""Conservative SQL statement-shape predicate, independent of deployment state."""

import re
import sqlparse
from sqlparse import tokens as sql_tokens

# Safe read-only SQL statement types
SAFE_SQL_TYPES = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"}
_NESTED_WRITE_DML_TYPES = {"INSERT", "UPDATE", "DELETE", "REPLACE", "MERGE"}
_EXECUTING_EXPLAIN_PATTERN = re.compile(
    r"^(?:EXPLAIN|DESCRIBE|DESC)\s+"
    r"(?:ANALYZE\b|\([^)]*\bANALYZE\b[^)]*\))",
    re.IGNORECASE,
)

_MYSQL_DASH_COMMENT_WHITESPACE = " \t\r\n\f\v"


def has_unsafe_mysql_comment_semantics(sql_query: str) -> bool:
    """Detect comment forms whose MySQL meaning differs from generic SQL parsing.

    MySQL executes the body of ``/*! ... */`` comments and interprets
    ``/*+ ... */`` as optimizer directives. MariaDB additionally executes
    ``/*M! ... */`` comments. MySQL also recognizes ``--`` comments only when
    the second dash is followed by whitespace or a control character, while
    sqlparse treats forms such as ``--1`` as a comment. Reject these forms
    before any comment-stripping normalization so policy checks cannot
    accidentally discard executable SQL or server directives.
    """
    try:
        statements = sqlparse.parse(sql_query)
        for statement in statements:
            for token in statement.flatten():
                if token.ttype not in sql_tokens.Comment:
                    continue

                comment = token.value.lstrip()
                if comment.startswith(("/*!", "/*+", "/*M!")):
                    return True
                if comment.startswith("--") and (
                    len(comment) == 2
                    or comment[2] not in _MYSQL_DASH_COMMENT_WHITESPACE
                ):
                    return True
    except Exception:
        # A syntax gate must fail closed if its parser cannot classify comments.
        return True
    return False


def _is_explain_for_connection(statement: sqlparse.sql.Statement) -> bool:
    """Detect MySQL's privilege-dependent inspection of another session."""
    tokens = [
        token
        for token in statement.flatten()
        if not token.is_whitespace and token.ttype not in sql_tokens.Comment
    ]
    if not tokens or tokens[0].normalized.upper() not in {
        "EXPLAIN",
        "DESCRIBE",
        "DESC",
    }:
        return False
    return any(
        token.normalized.upper() == "FOR"
        and tokens[index + 1].normalized.upper() == "CONNECTION"
        for index, token in enumerate(tokens[:-1])
    )


def is_sql_safe(sql_query: str) -> bool:
    """
    Checks if a given SQL query is safe by ensuring it only contains read-only statements.

    Allowed statement types for the current MySQL/SQLite runtime:
    - SELECT: Standard data retrieval
    - SHOW: Database metadata (SHOW TABLES, SHOW COLUMNS, etc.)
    - DESCRIBE: Table structure information
    - EXPLAIN: Non-ANALYZE execution-plan inspection

    ``EXPLAIN ANALYZE`` is rejected because supported MySQL versions can
    execute the analyzed statement. SELECT-shaped statements that contain a
    nested write DML token are also rejected. This remains a conservative
    syntax gate rather than comprehensive semantic SQL analysis.

    Args:
        sql_query: The SQL query to check.

    Returns:
        True if the query is safe (read-only), False otherwise.
    """
    if not sql_query:
        return True

    try:
        if has_unsafe_mysql_comment_semantics(sql_query):
            return False

        parsed = [
            statement
            for statement in sqlparse.parse(sql_query)
            if str(statement).strip(" \t\r\n;")
        ]
        # A raw query is one database operation. Besides simplifying audit and
        # timeout semantics, this prevents a safe first statement from hiding
        # a later statement from prefix-oriented policy checks.
        if len(parsed) != 1:
            return False

        for statement in parsed:
            if _is_explain_for_connection(statement):
                return False
            normalized_statement = sqlparse.format(
                str(statement),
                strip_comments=True,
            )
            normalized_statement = re.sub(
                r"\s+",
                " ",
                normalized_statement,
            ).strip()
            if _EXECUTING_EXPLAIN_PATTERN.match(normalized_statement):
                return False

            stmt_type = statement.get_type()
            # sqlparse returns 'UNKNOWN' for SHOW/DESCRIBE/EXPLAIN, check first token
            if stmt_type == "UNKNOWN" or stmt_type is None:
                first_token = statement.token_first(skip_cm=True)
                if first_token:
                    stmt_type = first_token.normalized.upper()
            if stmt_type not in SAFE_SQL_TYPES:
                return False
            if stmt_type == "SELECT" and any(
                token.ttype is sql_tokens.DML
                and token.normalized.upper() in _NESTED_WRITE_DML_TYPES
                for token in statement.flatten()
            ):
                return False
    except Exception:
        # In case of a parsing error, we consider it unsafe
        return False

    return True


# Example usage:
