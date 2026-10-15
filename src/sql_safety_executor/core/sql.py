"""Conservative SQL statement-shape predicate, independent of deployment state."""

import re
import sqlparse
from sqlparse import tokens as sql_tokens
from .decisions import PolicyDecision
from .structure import cte_declaration_token_ids, parse_with_clause, relation_name_token_ids, sql_token_upper

# Safe read-only SQL statement types
SAFE_SQL_TYPES = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"}
_NESTED_WRITE_DML_TYPES = {"INSERT", "UPDATE", "DELETE", "REPLACE", "MERGE"}
_EXECUTING_EXPLAIN_PATTERN = re.compile(
    r"^(?:EXPLAIN|DESCRIBE|DESC)\s+"
    r"(?:ANALYZE\b|\([^)]*\bANALYZE\b[^)]*\))",
    re.IGNORECASE | re.ASCII,
)

_MYSQL_DASH_COMMENT_WHITESPACE = " \t\r\n\f\v"


def _with_parse_failure() -> PolicyDecision:
    return PolicyDecision.deny(
        "sql_parse_failed", "Could not safely analyze this WITH statement.",
        "Keep the same connection. Check the CTE declarations, parentheses and read-only query bodies, or simplify to a supported read statement.",
    )


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
    if not tokens or sql_token_upper(tokens[0]) not in {
        "EXPLAIN",
        "DESCRIBE",
        "DESC",
    }:
        return False
    return any(
        sql_token_upper(token) == "FOR"
        and sql_token_upper(tokens[index + 1]) == "CONNECTION"
        for index, token in enumerate(tokens[:-1])
    )


def classify_sql_statement(sql_query: str) -> PolicyDecision:
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
        A structured statement-shape decision. Connection-specific structural
        and relation authorization checks are applied by the shared read policy.
    """
    if not sql_query or not sql_query.strip():
        return PolicyDecision.deny("empty_sql", "SQL query is empty.", "Send one read-only statement.")

    parsed: list[sqlparse.sql.Statement] = []
    try:
        if has_unsafe_mysql_comment_semantics(sql_query):
            return PolicyDecision.deny("unsafe_comment", "Ambiguous or executable MySQL comment syntax is not allowed")

        parsed = [
            statement
            for statement in sqlparse.parse(sql_query)
            if str(statement).strip(" \t\r\n;")
        ]
        # A raw query is one database operation. Besides simplifying audit and
        # timeout semantics, this prevents a safe first statement from hiding
        # a later statement from prefix-oriented policy checks.
        if len(parsed) != 1:
            return PolicyDecision.deny("multiple_statements", "Exactly one SQL statement is allowed per call.", "Send each statement in a separate call.")

        for statement in parsed:
            if _is_explain_for_connection(statement):
                return PolicyDecision.deny("session_inspection_denied", "Inspecting another database session is not allowed.")
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
                return PolicyDecision.deny("executing_explain_denied", "EXPLAIN ANALYZE is not allowed.", "Use EXPLAIN without ANALYZE.")

            clause = parse_with_clause(statement)
            stmt_type = statement.get_type()
            first_token = statement.token_first(skip_cm=True)
            # A complete lexical WITH header identifies the main command even
            # when keyword-like names or comments defeat Identifier grouping.
            # EXPLAIN remains non-executing; its explained DML is not a raw write.
            if clause is not None and first_token is not None and sql_token_upper(first_token) == "WITH":
                main = clause.query.parse().token_first(skip_cm=True)
                if main is None or main.ttype not in sql_tokens.Keyword.DML:
                    raise ValueError("Unsupported WITH main command")
                stmt_type = sql_token_upper(main)
            # sqlparse returns 'UNKNOWN' for SHOW/DESCRIBE/EXPLAIN, check first token
            if stmt_type == "UNKNOWN" or stmt_type is None:
                if first_token:
                    stmt_type = sql_token_upper(first_token)
                    if stmt_type == "WITH":
                        # UNKNOWN can result from a keyword-like CTE name or
                        # unsupported grouping. It does not establish a write,
                        # and WITH alone does not establish a safe read either.
                        return _with_parse_failure()
            if stmt_type not in SAFE_SQL_TYPES:
                if stmt_type == "PRAGMA":
                    return PolicyDecision.deny("pragma_statement_denied", "Raw PRAGMA statements are not allowed.", "Use list_tables() or describe_table(); describe_table() also returns indexes.")
                return PolicyDecision.deny("read_only_required", "Only read-only queries allowed (SELECT, DESCRIBE, non-ANALYZE EXPLAIN)", "For an intended write, discover reviewed mutation Skills with list_skills(); preview and obtain explicit approval before execution. Discovery does not authorize a write.")
            if stmt_type == "SELECT":
                declarations = cte_declaration_token_ids(statement)
                leaves = [t for t in statement.flatten() if not t.is_whitespace and t.ttype not in sql_tokens.Comment]
                writes = [t for t in leaves if id(t) not in declarations and t.ttype is sql_tokens.DML and sql_token_upper(t) in _NESTED_WRITE_DML_TYPES]
                if writes:
                    relation_names = relation_name_token_ids(statement)
                    if any(id(token) not in relation_names for token in writes):
                        return PolicyDecision.deny("nested_write_denied", "Write statements inside a read query are not allowed.")
    except Exception:
        # In case of a parsing error, we consider it unsafe
        if parsed:
            first = parsed[0].token_first(skip_cm=True)
            if first is not None and sql_token_upper(first) == "WITH":
                return _with_parse_failure()
        return PolicyDecision.deny("sql_parse_failed", "SQL statement could not be safely classified.")

    return PolicyDecision.allow()


def is_sql_safe(sql_query: str) -> bool:
    """Convenience predicate for the structured statement classifier."""
    return classify_sql_statement(sql_query).allowed


# Example usage:
