"""Regression query helper: all SQL executes through the complete core policy."""

import asyncio
from sql_safety_executor.core.queries import query
from sql_safety_executor.core.types import NullContext
from tests.support import make_gateway


def execute_sql(sql, connection_id=None):
    gateway = make_gateway()
    result = asyncio.run(
        query(gateway.runtime, sql, NullContext(), connection_id)
    ).structured_content
    if not result["success"]:
        return "Error: " + result["error"]
    return result["data"]

from sql_safety_executor.core.sql import is_sql_safe as is_sql_safe
from sql_safety_executor.core.sql import has_unsafe_mysql_comment_semantics as has_unsafe_mysql_comment_semantics
