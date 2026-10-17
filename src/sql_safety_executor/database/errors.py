"""Typed read failures with fixed public categories, independent of SQL text."""

import sqlite3

_MESSAGES = {
    "session_semantics_unavailable": "Execution session semantics could not be established.",
    "table_access_denied": "The resolved database object is not authorized.",
    "server_state_denied": "Server state access is not allowed through raw SQL.",
    "lock_function_denied": "Session lock functions are not allowed in read SQL.",
    "expensive_function_denied": "Delay and benchmark functions are not allowed in read SQL.",
    "file_operation_denied": "Server-side file operations are not allowed in read SQL.",
    "read_only_required": "Only read operations are allowed through this entry point.",
    "read_disabled": "Reading is disabled by the target connection policy.",
    "view_scope_unresolved": "The view authorization scope could not be determined within the supported limits.",
    "unknown_table": "Table not found.",
    "unknown_column": "Column not found.",
    "unknown_function": "SQL function not found for this database dialect.",
    "invalid_function_arguments": "SQL function arguments are invalid.",
    "incomplete_sql": "SQL statement is incomplete.",
    "sql_syntax_error": "SQL syntax error.",
    "query_timeout": "Query timeout exceeded.",
    "database_locked": "Database is locked.",
    "database_read_only": "Database is read-only.",
    "database_access_denied": "Database access denied.",
    "database_connection_failed": "Database connection failed.",
    "database_connection_lost": "Database connection was lost during the query.",
    "database_query_failed": "Database query failed.",
}

_HINTS = {
    "session_semantics_unavailable": "Keep the same connection; ask the maintainer to check its SQL mode and connection initialization.",
    "view_scope_unresolved": "Keep the same connection; use a supported reviewed view or ask the maintainer to review its dependency structure.",
    "unknown_table": "Use list_tables() to discover authorized tables on the same connection.",
    "unknown_column": "Use describe_table() to check columns on the same connection.",
    "unknown_function": "Use a function supported by the returned db_type; check the SQL dialect.",
    "invalid_function_arguments": "Check the function's arguments for the returned db_type.",
    "incomplete_sql": "Complete the statement and send one read-only query.",
    "sql_syntax_error": "Check SQL syntax for the returned db_type.",
}


class DatabaseQueryError(RuntimeError):
    """A read failed; only a known fixed category may cross the tool boundary."""

    def __init__(self, error_code: str = "database_query_failed"):
        if error_code not in _MESSAGES:
            raise ValueError("Unknown query error category")
        self.error_code = error_code
        self.hint = _HINTS.get(error_code)
        super().__init__(_MESSAGES[error_code])

    def error_payload(self) -> dict:
        payload = {"success": False, "error_code": self.error_code, "error": str(self)}
        if self.hint:
            payload["hint"] = self.hint
        return payload


def classify_database_error(error: Exception, db_type: str) -> DatabaseQueryError:
    """Inspect driver codes/prefixes without copying exception text to callers."""
    if isinstance(error, DatabaseQueryError):
        return error
    original = getattr(error, "orig", error)
    if db_type == "mysql":
        args = getattr(original, "args", ())
        code = args[0] if args and type(args[0]) is int else None
        category = {
            1054: "unknown_column", 1146: "unknown_table", 1109: "unknown_table",
            1305: "unknown_function", 1582: "invalid_function_arguments",
            1064: "sql_syntax_error", 1044: "database_access_denied", 1045: "database_access_denied",
            1142: "database_access_denied", 1143: "database_access_denied",
            1205: "database_locked", 1213: "database_locked", 3024: "query_timeout",
            1317: "query_timeout", 1969: "query_timeout", 2002: "database_connection_failed",
            2003: "database_connection_failed", 2006: "database_connection_lost",
            2013: "database_connection_lost",
        }.get(code) if code is not None else None
        return DatabaseQueryError(category or "database_query_failed")
    if db_type == "sqlite":
        code = getattr(original, "sqlite_errorcode", None)
        primary = code & 0xff if type(code) is int else None
        category = {
            sqlite3.SQLITE_BUSY: "database_locked", sqlite3.SQLITE_LOCKED: "database_locked",
            sqlite3.SQLITE_READONLY: "database_read_only", sqlite3.SQLITE_INTERRUPT: "query_timeout",
            sqlite3.SQLITE_AUTH: "database_access_denied", sqlite3.SQLITE_PERM: "database_access_denied",
            sqlite3.SQLITE_CANTOPEN: "database_connection_failed",
        }.get(primary) if primary is not None else None
        if category:
            return DatabaseQueryError(category)
        # SQLITE_ERROR covers many syntax/name errors; driver prefixes refine it.
        message = str(original).lower()
        for prefix, category in (
            ("no such table:", "unknown_table"), ("no such column:", "unknown_column"),
            ("no such function:", "unknown_function"), ("incomplete input", "incomplete_sql"),
            ("wrong number of arguments to function", "invalid_function_arguments"),
            ("database is locked", "database_locked"), ("interrupted", "query_timeout"),
            ("attempt to write a readonly database", "database_read_only"),
        ):
            if message.startswith(prefix):
                return DatabaseQueryError(category)
        if message.startswith("near ") and message.endswith("syntax error"):
            return DatabaseQueryError("sql_syntax_error")
    return DatabaseQueryError()
