"""Installed-resource and registration contracts, not model-behavior proofs."""

import shutil
import sqlite3

import pytest
from fastmcp import Client

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.mutations import execute_mutation_skill
from sql_safety_executor.core.types import NullContext, OperationError
from sql_safety_executor.prompts import render
from tests.support import ROOT
from tests.test_v38_config import bundle as bundle


@pytest.mark.asyncio
@pytest.mark.parametrize("skills_on,mutation_on,mrtr_on", [
    (False, False, False), (True, False, False),
    (True, True, False), (True, True, True),
])
async def test_independent_write_rules_follow_registration(
    bundle, tmp_path, skills_on, mutation_on, mrtr_on,
):
    _, _, skills, save = bundle
    empty_catalog = tmp_path / "trusted-skills"
    empty_catalog.mkdir()
    skills["skills"]["directory"] = str(empty_catalog)
    skills["skills"]["mutation"]["enabled"] = mutation_on
    skills["skills"]["mutation"]["mrtr"]["enabled"] = mrtr_on
    server = create_server(load_config(save(use_skills=skills_on)))
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    for name, enabled in (
        ("execute_mutation_skill", mutation_on),
        ("request_mutation_approval", mrtr_on),
    ):
        assert (name in tools) is enabled
        if enabled:
            # Each description must survive a Host hiding every other tool.
            assert render.text("mutation_results.md") in tools[name].description
            assert 'success="false" instead of a boolean' in tools[name].description
            assert 'affected row count not reported' in tools[name].description
    assert not (tmp_path / "db.sqlite").exists()


def test_missing_shared_write_rules_fail_server_creation(bundle, monkeypatch):
    _, _, skills, save = bundle
    skills["skills"]["mutation"]["mrtr"]["enabled"] = False
    original = render.text

    def missing(name):
        if name == "mutation_results.md":
            raise FileNotFoundError(name)
        return original(name)

    monkeypatch.setattr(render, "text", missing)
    with pytest.raises(FileNotFoundError, match="mutation_results.md"):
        create_server(load_config(save(use_skills=True)))


@pytest.mark.asyncio
async def test_mrtr_validation_failure_preserves_related_clue_without_proposal(bundle):
    _, connections, _, save = bundle
    connections["connections"]["demo"]["mutation"] = {
        "enabled": True,
        "skills": ["sample-update-order-status", "sample-reset-order-to-pending"],
    }
    config = load_config(save(use_skills=True))
    database = config.connections["demo"].sqlite_database_path
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, status TEXT)")
        db.execute("INSERT INTO orders VALUES(1, 'pending')")
    server = create_server(config)

    async def unexpected_approval(*args):
        pytest.fail("a validation failure must not request approval")

    async with Client(server, elicitation_handler=unexpected_approval) as client:
        result = await client.call_tool("request_mutation_approval", {
            "skill_name": "sample-update-order-status",
            "params": {"order_id": 1, "new_status": "shipped"},
            "connection_id": "demo",
        })
        payload = result.structured_content
        assert payload["success"] is False
        assert payload["error_code"] == "validation_failed"
        assert payload["execution_outcome"] == "not_executed"
        assert payload["related_available_skills"] == ["sample-reset-order-to-pending"]
        assert "preview_token" not in payload
        assert len(server.gateway_runtime.tokens) == 0
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT status FROM orders").fetchone() == ("pending",)


@pytest.mark.asyncio
async def test_imperative_revalidation_failure_keeps_clue_and_consumes_token(
    bundle, tmp_path,
):
    _, connections, skills, save = bundle
    skill_name = "checkpoint-order"
    root = tmp_path / "trusted-skills"
    custom = root / skill_name
    custom.mkdir(parents=True)
    shutil.copytree(ROOT / "skills/sample-reset-order-to-pending",
                    root / "sample-reset-order-to-pending")
    (custom / "skill_def.md").write_text(
        "---\nname: checkpoint-order\ntype: mutation\nsource: mutation.py\n"
        "risk: medium\nrequires_confirmation: true\ntables: [orders]\n"
        "related_skills: [sample-reset-order-to-pending]\nparams: {}\n---\n",
        encoding="utf-8",
    )
    (custom / "mutation.py").write_text(
        "from sql_safety_executor.skills import MutationBase\n"
        "class Mutation(MutationBase):\n"
        "    def validate(self, params):\n"
        "        rows = self.adapter.execute('SELECT status FROM orders WHERE id=1')\n"
        "        return {'valid': rows[0][0] == 'pending'}\n"
        "    def preview(self, params): return {'affected_rows_estimate': 1}\n"
        "    def execute(self, params): raise AssertionError('must fail before execute')\n",
        encoding="utf-8",
    )
    skills["skills"]["directory"] = str(root)
    connections["connections"]["demo"]["mutation"] = {
        "enabled": True, "skills": [skill_name, "sample-reset-order-to-pending"],
    }
    config = load_config(save(use_skills=True))
    database = config.connections["demo"].sqlite_database_path
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, status TEXT)")
        db.execute("INSERT INTO orders VALUES(1, 'pending')")
    server = create_server(config)
    runtime = server.gateway_runtime
    try:
        preview = await execute_mutation_skill(
            runtime, skill_name, {}, NullContext(), connection_id="demo",
        )
        token = preview.structured_content["preview_token"]
        assert len(runtime.tokens) == 1
        # An external writer changes the precondition after preview.
        with sqlite3.connect(database) as db:
            db.execute("UPDATE orders SET status='confirmed' WHERE id=1")
        result = await execute_mutation_skill(
            runtime, skill_name, {}, NullContext(), confirm=True,
            preview_token=token, connection_id="demo",
        )
        payload = result.structured_content
        assert payload["success"] is False
        assert payload["mode"] == "execute"
        assert payload["error_code"] == "validation_failed"
        assert payload["execution_outcome"] == "not_executed"
        assert payload["related_available_skills"] == ["sample-reset-order-to-pending"]
        assert result.meta["preview_token_consumed"] is True
        assert len(runtime.tokens) == 0
        with pytest.raises(OperationError, match="already been used"):
            await execute_mutation_skill(
                runtime, skill_name, {}, NullContext(), confirm=True,
                preview_token=token, connection_id="demo",
            )
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT status FROM orders").fetchone() == ("confirmed",)
    finally:
        runtime.close()
