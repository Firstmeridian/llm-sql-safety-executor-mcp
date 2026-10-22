"""Statement-shape convenience over the same analysis used by scoped reads."""
from .analysis import analyze_sql
from .decisions import PolicyDecision
from .policy import classify_analysis
from sql_safety_executor.database.semantics import DialectContext


def classify_sql_statement(sql_query: str, *, context: DialectContext | None = None) -> PolicyDecision:
    """Classify shape only; this grants neither relation nor connection access.

    A supplied context selects exactly one interpretation. Standalone callers
    can recognize read shapes from either supported backend; execution always
    goes through the target-bound shared project policy instead.
    """
    contexts = [context] if context is not None else [DialectContext("sqlite"), DialectContext("mysql")]
    decisions = [classify_analysis(analyze_sql(sql_query, candidate)) for candidate in contexts]
    for decision in decisions:
        if decision.error_code in {"unsafe_comment", "multiple_statements"}:
            return decision
    return next((decision for decision in decisions if decision.allowed), decisions[0])


def has_unsafe_mysql_comment_semantics(sql_query: str) -> bool:
    return analyze_sql(sql_query, DialectContext("mysql")).statement_kind == "unsafe_comment"


def is_sql_safe(sql_query: str) -> bool:
    return classify_sql_statement(sql_query).allowed
