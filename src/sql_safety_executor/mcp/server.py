"""FastMCP composition root; application services remain protocol-independent."""

from __future__ import annotations

from .contracts import TOOL_DEFINITIONS
from .context import ToolContext
from .bootstrap import prepare_framework

prepare_framework()

import inspect
from contextlib import asynccontextmanager
from typing import Annotated, get_type_hints

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import ToolResult
from mcp.server.request_state import RequestStateSecurity
from mcp.types import ToolAnnotations
from pydantic import Field

from sql_safety_executor.config import AppConfig
from sql_safety_executor.core import diagnostics, mutations, queries, schema
from sql_safety_executor.core.runtime import GatewayRuntime
from sql_safety_executor.core.types import OperationError
from sql_safety_executor.database.diagnostics import ConnectionReport
from sql_safety_executor.prompts import render
from sql_safety_executor.skills import tools as skill_tools


def _handler(function, runtime):
    async def handler(**kwargs):
        try:
            kwargs["ctx"] = ToolContext(kwargs["ctx"])
            result = await function(runtime, **kwargs)
            return ToolResult(
                structured_content=result.structured_content, meta=result.meta
            )
        except OperationError as exc:
            raise ToolError(str(exc)) from None

    hints = get_type_hints(function, include_extras=True)
    params = []
    for name, param in inspect.signature(function).parameters.items():
        if name == "runtime":
            continue
        annotation = Context if name == "ctx" else hints.get(name, param.annotation)
        default = param.default
        if function.__name__ == "list_skills" and name == "detail_level":
            default = runtime.config.skills.discovery.default_detail
        if function.__name__ == "list_skills" and name == "available_only":
            default = runtime.config.skills.discovery.available_only
        if name == "sql":
            maximum = runtime.config.server.limits.sql_chars
            annotation = Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=maximum or None,
                    description="Read-only SQL query (SELECT, DESCRIBE or non-ANALYZE EXPLAIN).",
                ),
            ]
        params.append(param.replace(annotation=annotation, default=default))
    handler.__name__ = function.__name__
    handler.__signature__ = inspect.Signature(params, return_annotation=ToolResult)
    handler.__annotations__ = {p.name: p.annotation for p in params}
    handler.__annotations__["return"] = ToolResult
    return handler


def create_server(config: AppConfig) -> FastMCP:
    runtime = GatewayRuntime(config)

    @asynccontextmanager
    async def lifespan(server):
        try:
            runtime.start()
            yield {"runtime": runtime}
        finally:
            runtime.close()

    try:
        server = FastMCP(
            name="sql-safety-executor",
            version="3.8.0",
            instructions=render.instructions(config),
            lifespan=lifespan,
            mask_error_details=True,
            strict_input_validation=True,
            tasks=False,
            cache_ttl=None,
            request_state_security=RequestStateSecurity.ephemeral(
                ttl=config.skills.mutation.preview.ttl_seconds
            ),
        )
        definitions = TOOL_DEFINITIONS
        functions = [
            diagnostics.list_connections,
            queries.query,
            diagnostics.check_connection,
            schema.list_tables,
            schema.describe_table,
            schema.get_full_schema,
        ]
        if config.server.tools.table_summary:
            functions.append(schema.get_table_summary)
        if config.server.tools.schema_enabled:
            functions.append(schema.sample)
        if config.skills.enabled:
            functions.extend(
                [
                    skill_tools.list_skills,
                    skill_tools.get_skill_detail,
                    skill_tools.execute_query_skill,
                ]
            )
            if config.skills.mutation.enabled:
                functions.append(mutations.execute_mutation_skill)
        for function in functions:
            spec = definitions[function.__name__]
            output_schema = spec.get("output_schema")
            if output_schema == "$ConnectionReport":
                output_schema = ConnectionReport.model_json_schema()
            annotations = ToolAnnotations.model_validate(spec["annotations"])
            server.tool(
                _handler(function, runtime),
                name=function.__name__,
                description=render.text(f"tools/{function.__name__}.md"),
                annotations=annotations,
                output_schema=output_schema,
                timeout=runtime.tool_timeout,
            )
        if config.skills.mutation.mrtr.enabled:
            from .mrtr import register_mrtr

            register_mrtr(server, runtime)
        if config.server.observability.telemetry.enabled:
            from sql_safety_executor.observability.telemetry import (
                ToolTelemetryMiddleware,
            )

            server.add_middleware(ToolTelemetryMiddleware(runtime))

        assistant_prompt = render.assistant(config)

        @server.prompt(name="sql_assistant")
        def sql_assistant() -> str:
            """System prompt for SQL query assistance."""
            return assistant_prompt

        setattr(server, "gateway_runtime", runtime)
        return server
    except BaseException:
        runtime.close()
        raise
