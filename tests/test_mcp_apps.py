"""Opt-in MCP Apps result viewer: wire contract, fallback and View safety invariants."""

import re

import pytest
from fastmcp import Client
from sql_safety_executor import create_server, load_config
from sql_safety_executor.config.loader import ConfigError, explain_config
from sql_safety_executor.mcp.apps import RESULT_VIEWER_URI, result_viewer_html
from tests.test_v38_config import bundle as bundle
from tests.test_v38_mrtr import SKILL


def _server(bundle, *, apps=None, mrtr=False):
    server, connections, skills, save = bundle
    target = connections["connections"]["demo"]
    target["read"] = {"mode": "all"}
    if apps is not None:
        server["apps"] = apps
    if mrtr:
        target["mutation"] = {"enabled": True, "skills": [SKILL]}
    else:
        skills["skills"]["mutation"]["mrtr"] = {"enabled": False}
    return create_server(load_config(save(use_skills=True)))


@pytest.mark.asyncio
async def test_apps_default_off_adds_no_ui_metadata_or_resources(bundle):
    server = _server(bundle)
    try:
        assert explain_config(server.gateway_runtime.config)["apps.enabled"] == {
            "value": False,
            "source": "builtin_default",
        }
        async with Client(server) as client:
            tools = await client.list_tools()
            assert all("ui" not in (tool.meta or {}) for tool in tools)
            assert await client.list_resources() == []
    finally:
        server.gateway_runtime.close()


@pytest.mark.asyncio
async def test_enabled_binds_read_tools_and_hides_every_tool_from_the_view(bundle):
    server = _server(bundle, apps={"enabled": True}, mrtr=True)
    try:
        async with Client(server) as client:
            tools = {tool.name: tool.meta["ui"] for tool in await client.list_tools()}
            assert {"execute_mutation_skill", "request_mutation_approval"} <= set(tools)
            for name, ui in tools.items():
                assert ui["visibility"] == ["model"], name
                if name in {"query", "execute_query_skill"}:
                    assert ui["resourceUri"] == RESULT_VIEWER_URI
                else:
                    assert "resourceUri" not in ui, name

            [listed] = await client.list_resources()
            assert str(listed.uri) == RESULT_VIEWER_URI
            [content] = await client.read_resource(RESULT_VIEWER_URI)
            assert content.mime_type == "text/html;profile=mcp-app"
            # Explicit empty CSP: no external connect/resource/frame origins.
            assert content.meta["ui"] == {"csp": {}, "prefersBorder": True}
            assert content.text == result_viewer_html()
    finally:
        server.gateway_runtime.close()


@pytest.mark.asyncio
async def test_ui_bound_query_keeps_text_fallback_and_unchanged_payload(bundle):
    server = _server(bundle, apps={"enabled": True})
    try:
        async with Client(server) as client:
            result = await client.call_tool("query", {"sql": "SELECT 1 AS one"})
            assert result.structured_content["data"] == [{"one": 1}]
            assert '"data":[{"one":1}]' in result.content[0].text
            rejected = await client.call_tool(
                "query", {"sql": "DELETE FROM missing"}, raise_on_error=False
            )
            assert rejected.structured_content["success"] is False
    finally:
        server.gateway_runtime.close()


@pytest.mark.parametrize("value", ["true", 1, {"enabled": "true"}, {"typo": True}])
def test_apps_config_is_strict(bundle, value):
    server, _, _, save = bundle
    server["apps"] = value if isinstance(value, dict) else {"enabled": value}
    with pytest.raises(ConfigError):
        load_config(save())


def test_viewer_html_is_self_contained_and_display_only():
    html = result_viewer_html()
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html)
    assert policy is not None
    directives = policy.group(1)
    for directive in (
        "default-src 'none'",
        "connect-src 'none'",
        "frame-src 'none'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    ):
        assert directive in directives
    # Untrusted row values are rendered with textContent only.
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "http://",
        "https://",
        "<link",
        "<iframe",
        "src=",
        '"tools/call"',
        '"resources/read"',
        '"ui/message"',
        '"ui/open-link"',
        '"ui/update-model-context"',
    ):
        assert forbidden not in html, forbidden
    for method in (
        '"ui/initialize"',
        '"ui/notifications/initialized"',
        "ui/notifications/tool-result",
        "ui/notifications/size-changed",
        "event.source !== window.parent",
    ):
        assert method in html
