"""Opt-in, display-only MCP Apps (io.modelcontextprotocol/ui) result viewer.

The View renders only the tool result the Host already received. It declares
no network origins, calls no tools, sends no chat messages and never updates
model context. Policy, truncation and write gates stay in the core services.
"""

from importlib.resources import files

from fastmcp.apps import UI_MIME_TYPE, AppConfig, ResourceCSP

RESULT_VIEWER_URI = "ui://sql-safety-executor/result-viewer.html"
# Tools whose tabular `data` payload the viewer renders.
VIEWER_TOOLS = frozenset({"query", "execute_query_skill"})
# The View is passive, so no gateway tool is callable from it.
MODEL_ONLY: list = ["model"]


def result_viewer_html() -> str:
    return (
        files("sql_safety_executor.mcp")
        .joinpath("ui/result_viewer.html")
        .read_text(encoding="utf-8")
    )


def tool_app(name: str, enabled: bool) -> AppConfig | None:
    if not enabled:
        return None
    return AppConfig(
        resource_uri=RESULT_VIEWER_URI if name in VIEWER_TOOLS else None,
        visibility=MODEL_ONLY,
    )


def register_apps(server) -> None:
    html = result_viewer_html()

    @server.resource(
        RESULT_VIEWER_URI,
        name="sql_result_viewer",
        title="SQL Result Viewer",
        description="Read-only table view for query and Query Skill results.",
        mime_type=UI_MIME_TYPE,
        app=AppConfig(csp=ResourceCSP(), prefers_border=True),
    )
    def sql_result_viewer() -> str:
        return html
