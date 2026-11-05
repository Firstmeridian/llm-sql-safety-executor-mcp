"""MRTR proposals across same-process managed mutation Skill publications."""

import asyncio
import shutil
import sqlite3
from pathlib import Path

import pytest
from mcp.types import ElicitResult, InputRequiredResult

from sql_safety_executor import create_server, load_config
from sql_safety_executor.core.types import NullContext, OperationError
from sql_safety_executor.mcp.mrtr import request_approval
from tests.test_v38_config import bundle as bundle

SKILL = "sample-update-order-status"
PARAMS = {"order_id": 1, "new_status": "confirmed"}


class Context(NullContext):
    def __init__(self, state=None, answer=None):
        from types import SimpleNamespace

        self.request_context = SimpleNamespace(protocol_version="2026-07-28")
        self.session = SimpleNamespace(
            client_capabilities=SimpleNamespace(
                elicitation=SimpleNamespace(form={})
            )
        )
        self.request_state = state
        self.input_responses = answer


@pytest.fixture
def deployment(bundle, tmp_path):
    _, connections, skills, save = bundle
    source = Path(__file__).resolve().parents[1] / "skills" / SKILL
    root = tmp_path / "skills"
    root.mkdir()
    shutil.copytree(source, root / SKILL)
    skills["skills"]["directory"] = str(root)
    skills["skills"]["mutation"]["enabled"] = True
    skills["skills"]["mutation"]["allowed_connections"] = ["demo"]
    skills["skills"]["mutation"]["mrtr"]["enabled"] = True
    connections["connections"]["demo"]["read"] = {
        "mode": "allowlist",
        "tables": ["orders"],
    }
    connections["connections"]["demo"]["mutation"] = {
        "enabled": True,
        "skills": [SKILL],
    }
    db_path = tmp_path / "db.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute(
            "CREATE TABLE orders(id INTEGER PRIMARY KEY, order_date TEXT, "
            "amount REAL, total_amount REAL, status TEXT)"
        )
        db.execute("INSERT INTO orders VALUES(1,'2026-01-15',10,10,'pending')")
    server = create_server(load_config(save(use_skills=True)))
    yield server, root
    server.gateway_runtime.close()


def current_status(server):
    path = server.gateway_runtime.config.connections["demo"].sqlite_database_path
    with sqlite3.connect(path) as db:
        return db.execute("SELECT status FROM orders WHERE id=1").fetchone()[0]


async def propose(server, ctx=None):
    runtime = server.gateway_runtime
    with runtime.catalog_snapshot():
        return await request_approval(runtime, SKILL, PARAMS, ctx or Context(), "demo")


async def reload_mutations(server):
    return server.gateway_runtime.reload_skills("mutation")


def change_entry(root):
    definition = root / SKILL / "skill_def.md"
    original = definition.read_text(encoding="utf-8")
    # Change the catalog entry while retaining the hand-authored Skill version.
    changed = original.replace(
        "Update order status one step along",
        "Update order status carefully along",
        1,
    )
    assert changed != original
    definition.write_text(changed, encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize("continuation", ["reask", "accept", "decline"])
async def test_changed_entry_rejects_pending_mrtr_proposal(deployment, continuation):
    server, root = deployment
    first = await propose(server)
    assert isinstance(first, InputRequiredResult)
    original_version = server.gateway_runtime.catalog.get_skills_cache()[SKILL].version
    change_entry(root)
    publication = await reload_mutations(server)
    assert publication["success"]
    assert publication["changed"] == [SKILL]
    assert server.gateway_runtime.catalog.get_skills_cache()[SKILL].version == original_version

    if continuation == "reask":
        ctx = Context(first.request_state)
    else:
        action, content = (
            ("accept", {"approve": True})
            if continuation == "accept"
            else ("decline", None)
        )
        ctx = Context(
            first.request_state,
            {"approval": ElicitResult(action=action, content=content)},
        )
    with pytest.raises(OperationError):
        await propose(server, ctx)
    assert current_status(server) == "pending"


@pytest.mark.asyncio
async def test_noop_mutation_reload_preserves_pending_mrtr_proposal(deployment):
    server, _ = deployment
    first = await propose(server)
    assert isinstance(first, InputRequiredResult)
    before = server.gateway_runtime.catalog.get_skills_cache()[SKILL]._mutation_generation
    publication = await reload_mutations(server)
    assert publication["success"]
    after = server.gateway_runtime.catalog.get_skills_cache()[SKILL]._mutation_generation
    assert after == before

    yes = {"approval": ElicitResult(action="accept", content={"approve": True})}
    result = await propose(server, Context(first.request_state, yes))
    assert result.structured_content["execution_outcome"] == "committed"
    assert current_status(server) == "confirmed"


@pytest.mark.asyncio
async def test_old_catalog_request_held_before_prepare_cannot_issue_stale_proposal(
    deployment, monkeypatch
):
    server, root = deployment
    entered_prepare, continue_prepare = asyncio.Event(), asyncio.Event()
    from sql_safety_executor.core.mutation_service import MutationService

    original_prepare = MutationService.prepare

    async def held_prepare(self, *args, **kwargs):
        entered_prepare.set()
        await continue_prepare.wait()
        return await original_prepare(self, *args, **kwargs)

    monkeypatch.setattr(MutationService, "prepare", held_prepare)
    task = asyncio.create_task(propose(server))
    try:
        await asyncio.wait_for(entered_prepare.wait(), timeout=10)
        change_entry(root)
        publication = await asyncio.wait_for(reload_mutations(server), timeout=10)
        assert publication["success"]
        assert publication["changed"] == [SKILL]
        continue_prepare.set()
        with pytest.raises(OperationError):
            await asyncio.wait_for(task, timeout=10)
        assert len(server.gateway_runtime.tokens) == 0
        assert current_status(server) == "pending"
    finally:
        continue_prepare.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
