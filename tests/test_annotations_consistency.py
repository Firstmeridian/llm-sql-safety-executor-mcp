"""
Annotation consistency lint for all registered MCP tools.

Goal: prevent regressions where a newly added tool forgets to declare
`openWorldHint` (or accidentally copy-pastes `openWorldHint=False` when the
tool actually does reach external systems). This is a CI guardrail, not a
runtime security control — MCP ToolAnnotations are advisory hints.

Policy:
- Every registered tool MUST appear in `_EXPECTED_ANNOTATIONS`.
- The recorded annotations must match exactly.
- Adding a new tool requires updating this allowlist explicitly (the test
  fails until you do so), forcing a code-review touchpoint.

When adding a tool that reaches outside the configured database boundary
(external HTTP API, webhook, third-party service, cross-instance DB call,
etc.), set `openWorldHint=True` for that tool and add the entry here with
that value.
"""

from __future__ import annotations

from tests.support import SCENARIO, make_gateway

import asyncio

from mcp.types import Tool
import pytest


# Expected annotations for every registered MCP tool.
# Tuple format: (readOnlyHint, destructiveHint, idempotentHint, openWorldHint)
_EXPECTED_ANNOTATIONS: dict[str, tuple[bool, bool, bool, bool]] = {
    "list_connections":       (True,  False, True,  False),
    "query":                  (True,  False, True,  False),
    "check_connection":       (True,  False, True,  False),
    "list_tables":            (True,  False, True,  False),
    "describe_table":         (True,  False, True,  False),
    "get_full_schema":        (True,  False, True,  False),
    "get_table_summary":      (True,  False, True,  False),
    "sample":                 (True,  False, True,  False),
    "list_skills":            (True,  False, True,  False),
    "get_skill_detail":       (True,  False, True,  False),
    "execute_query_skill":    (True,  False, True,  False),
    "execute_mutation_skill": (False, True,  False, False),
}


@pytest.fixture
def all_tools_server(monkeypatch):
    """Import mcp_sql_server with every tool enabled for full enumeration."""
    monkeypatch.setitem(SCENARIO, "ENABLE_SKILLS", "1")
    monkeypatch.setitem(SCENARIO, "SKILLS_ALLOW_MUTATIONS", "1")
    monkeypatch.setitem(SCENARIO, "ENABLE_SCHEMA_TOOLS", "1")
    monkeypatch.setitem(SCENARIO, "ENABLE_TABLE_SUMMARY", "1")
    monkeypatch.setitem(SCENARIO, "DB_TYPE", "sqlite")
    monkeypatch.setitem(SCENARIO, "SQLITE_DATABASE_PATH", ":memory:")
    monkeypatch.setitem(SCENARIO, "SKILLS_DIR", "skills/")
    monkeypatch.setitem(SCENARIO, "SKILLS_EXCLUDE_PROFILES", "")
    monkeypatch.setitem(SCENARIO, "SKILLS_AUDIT_QUERIES", "0")
    monkeypatch.setitem(SCENARIO, "MAX_SQL_LENGTH", "20000")
    monkeypatch.setitem(SCENARIO, "MCP_TOOL_TIMEOUT_SECONDS", "120")
    monkeypatch.delitem(SCENARIO, "SKILLS_LIST_DEFAULT_DETAIL", raising=False)
    monkeypatch.delitem(SCENARIO, "SKILLS_LIST_AVAILABLE_ONLY_DEFAULT", raising=False)
    monkeypatch.delitem(SCENARIO, "SKILLS_CHECK_SCHEMA_ON_LIST", raising=False)

    # skill_loader lives under skills/_lib and is sys.path-extended by
    # mcp_sql_server at import time. Pre-extend here so we can patch it first.
    from tests import support_catalog as skill_loader
    monkeypatch.setattr(skill_loader, "generate_skills_md", lambda *_a, **_k: None)

    module = make_gateway()
    yield module


def _collect_tools(server_module) -> dict[str, Tool]:
    tools = asyncio.run(server_module.mcp.list_tools())
    return {tool.name: tool for tool in tools}


def test_every_registered_tool_has_explicit_annotations(all_tools_server):
    """Every tool must declare readOnlyHint, destructiveHint, idempotentHint, openWorldHint."""
    tools = _collect_tools(all_tools_server)
    for name, tool in tools.items():
        annotations = tool.annotations
        assert annotations is not None, f"{name}: missing ToolAnnotations"
        assert annotations.read_only_hint is not None, f"{name}: readOnlyHint not declared"
        assert annotations.destructive_hint is not None, f"{name}: destructiveHint not declared"
        assert annotations.idempotent_hint is not None, f"{name}: idempotentHint not declared"
        assert annotations.open_world_hint is not None, f"{name}: openWorldHint not declared"


def test_registered_tools_match_expected_allowlist(all_tools_server):
    """
    Tool inventory and annotations must match `_EXPECTED_ANNOTATIONS` exactly.

    If this fails:
      - You added a new tool: add it to `_EXPECTED_ANNOTATIONS` with the correct
        annotations. If the tool reaches outside the configured DB boundary,
        set `openWorldHint=True`.
      - You removed a tool: delete its entry from `_EXPECTED_ANNOTATIONS`.
      - You changed an existing tool's annotations: update the expected tuple
        and review whether the new semantics are correct.
    """
    tools = _collect_tools(all_tools_server)
    registered = set(tools.keys())
    expected = set(_EXPECTED_ANNOTATIONS.keys())

    missing_in_expected = registered - expected
    missing_in_registered = expected - registered
    assert not missing_in_expected, (
        f"New tool(s) without allowlist entry: {sorted(missing_in_expected)}. "
        f"Update _EXPECTED_ANNOTATIONS in {__file__}."
    )
    assert not missing_in_registered, (
        f"Allowlist references non-existent tool(s): {sorted(missing_in_registered)}. "
        f"Remove stale entries from _EXPECTED_ANNOTATIONS."
    )

    mismatches: list[str] = []
    for name, expected_tuple in _EXPECTED_ANNOTATIONS.items():
        annotations = tools[name].annotations
        assert annotations is not None, f"{name}: missing ToolAnnotations"
        actual_tuple = (
            annotations.read_only_hint,
            annotations.destructive_hint,
            annotations.idempotent_hint,
            annotations.open_world_hint,
        )
        if actual_tuple != expected_tuple:
            mismatches.append(
                f"  {name}: expected {expected_tuple}, got {actual_tuple}"
            )
    assert not mismatches, (
        "Annotation mismatch:\n" + "\n".join(mismatches)
    )


def test_closed_world_hint_is_uniform(all_tools_server):
    """
    Current policy: every tool operates inside the configured DB boundary, so
    `openWorldHint=False` is uniform. If a future tool legitimately needs
    `openWorldHint=True`, update both `_EXPECTED_ANNOTATIONS` and this test's
    docstring with the rationale.
    """
    tools = _collect_tools(all_tools_server)
    open_world_tools = [
        name for name, tool in tools.items()
        if tool.annotations and tool.annotations.open_world_hint is True
    ]
    assert open_world_tools == [], (
        f"Tools with openWorldHint=True: {open_world_tools}. "
        f"If this is intentional, document the rationale in "
        f"test_annotations_consistency.py and remove this uniformity check."
    )
