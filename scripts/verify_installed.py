#!/usr/bin/env python3
"""Run with an isolated wheel interpreter; validate imports/prompts/stdio from /tmp."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


async def check(directory):
    from sql_safety_executor.mcp.bootstrap import prepare_framework

    prepare_framework()
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    import sql_safety_executor

    assert "site-packages" in sql_safety_executor.__file__, sql_safety_executor.__file__
    config = directory / "server.toml"
    config.write_text(
        'schema_version=1\n[files]\nconnections="connections.toml"\n[server]\ndefault_connection="test"\n'
    )
    (directory / "connections.toml").write_text(
        'schema_version=1\n[connections.test]\ntype="sqlite"\nsqlite.path=":memory:"\nread.mode="all"\n'
    )
    (directory / ".env").write_text("FASTMCP_STRICT_INPUT_VALIDATION=invalid\n")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "sql_safety_executor",
            "config",
            "check",
            "--config",
            str(config),
        ],
        check=True,
        cwd=directory,
    )
    for mode, protocol in [("auto", "2026-07-28"), ("legacy", "2025-11-25")]:
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "sql_safety_executor", "serve", "--config", str(config)],
            cwd=str(directory),
        )
        async with Client(transport, mode=mode) as client:
            assert client.protocol_version == protocol
            assert "connection_id" in str(await client.get_prompt("sql_assistant"))
            result = await client.call_tool("query", {"sql": "SELECT 1 AS value"})
            assert result.structured_content["data"] == [{"value": 1}]

    # Exercise optional write descriptions from the installed wheel without
    # opening a database or invoking any preview/execute callback.
    skill = directory / "wheel-skills" / "wheel-probe"
    skill.mkdir(parents=True)
    (skill / "skill_def.md").write_text(
        "---\nname: wheel-probe\ntype: mutation\nsource: mutation.py\n"
        "risk: low\nrequires_confirmation: true\nparams: {}\n---\nWheel probe.\n",
        encoding="utf-8",
    )
    (skill / "mutation.py").write_text(
        "from sql_safety_executor.skills import ManagedMutationBase, ManagedMutationPlan\n"
        "class Mutation(ManagedMutationBase):\n"
        "    managed_plan = ManagedMutationPlan(\n"
        "        sql='INSERT INTO probe VALUES (1)', parameters=(), expected_rowcount=1)\n"
        "    def validate(self, params): raise AssertionError('enumeration only')\n"
        "    def preview(self, params): raise AssertionError('enumeration only')\n",
        encoding="utf-8",
    )
    config.write_text(
        'schema_version=1\n[files]\nconnections="connections.toml"\nskills="skills.toml"\n'
        '[server]\ndefault_connection="test"\n', encoding="utf-8",
    )
    (directory / "connections.toml").write_text(
        'schema_version=1\n[connections.test]\ntype="sqlite"\n'
        'sqlite.path="must-not-open.sqlite"\nread.mode="deny"\n'
        'mutation.enabled=true\nmutation.skills=["wheel-probe"]\n', encoding="utf-8",
    )
    (directory / "skills.toml").write_text(
        'schema_version=1\n[skills]\nenabled=true\ndirectory="wheel-skills"\n'
        '[skills.audit]\npath="wheel-audit.jsonl"\n'
        '[skills.mutation]\nenabled=true\nallowed_connections=["test"]\n'
        '[skills.mutation.mrtr]\nenabled=true\n', encoding="utf-8",
    )
    from sql_safety_executor.prompts.render import text
    shared = text("mutation_results.md")
    for mode in ("auto", "legacy"):
        transport = StdioTransport(
            command=sys.executable,
            args=["-m", "sql_safety_executor", "serve", "--config", str(config)],
            cwd=str(directory),
        )
        async with Client(transport, mode=mode) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            for name in ("execute_mutation_skill", "request_mutation_approval"):
                description = tools[name].description or ""
                assert shared in description
                assert "committed: written, even when success=false" in description
                assert "distinguish what the payload reports from what it confirms" in description
                assert "report both the material payload claim" in description
                assert "other target/Skill reports committed" in description
                assert "payload claims committed; execution is unconfirmed" in description
                assert "affected row count not reported" in description
                assert "Abandoning a proposal does not revoke its server token" in description
                if name == "execute_mutation_skill":
                    expiry = tools[name].output_schema["properties"]["preview_token_expires_at"]
                    assert expiry["type"] == "string"
                    assert "timestamp and timezone" in expiry["description"]
                    assert "if absent" in expiry["description"]
                    assert "Do not infer current token validity" in expiry["description"]
                    assert "preview_token_expires_at" not in tools[name].output_schema.get("required", [])
                    assert "show returned preview_token_expires_at and timezone" in description
                    assert "or report expiry missing" in description
                    assert 'Do not infer "valid"/"expired" from timestamps' in description
                    assert "Only execute checks validity; no automatic new preview" in description
            for name in ("query", "sample", "execute_query_skill"):
                # Shared source, independently visible descriptions.
                assert text("read_results.md") in (tools[name].description or "")
                assert "without guessing a unit" in (tools[name].description or "")
            assert "execute_mutation_skill result rules" not in (
                tools["request_mutation_approval"].description or ""
            )
    assert not (directory / "must-not-open.sqlite").exists()
    print(
        json.dumps(
            {
                "wheel": sql_safety_executor.__version__,
                "outside_repository": True,
                "protocols": ["2026-07-28", "2025-11-25"],
                "packaged_prompts": True,
                "independent_mutation_descriptions": True,
                "expiry_output_field_guidance": True,
            }
        )
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="sql-wheel-") as folder:
        os.chdir(folder)
        asyncio.run(check(Path(folder)))
