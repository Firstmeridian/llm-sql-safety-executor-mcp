"""Same-session publication, rejected candidates and preserved write state."""

import asyncio
import shutil
import sqlite3
from pathlib import Path

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from sql_safety_executor.skills.catalog import SkillReloadError
from tests.test_v38_config import bundle as bundle


def write_query(root, name="report", sql="SELECT :n AS n", params=True):
    directory = root / name
    directory.mkdir(exist_ok=True)
    (directory / "skill_def.md").write_text(
        f"---\nname: {name}\ntype: query\nsource: query.sql\nrisk: low\n"
        "description: A reloadable report\ndatabases: [sqlite]\n"
        + ("params:\n  n: {type: int, required: true}\n" if params else "params: {}\n")
        + "---\n", encoding="utf-8")
    (directory / "query.sql").write_text(sql, encoding="utf-8")
    return directory


@pytest.fixture
def deployment(bundle, tmp_path):
    _, connections, skills, save = bundle
    root = tmp_path / "skills"
    root.mkdir()
    write_query(root)
    skills["skills"]["directory"] = str(root)
    skills["skills"]["mutation"]["mrtr"]["enabled"] = False
    connections["connections"]["demo"]["read"] = {"mode": "allowlist", "tables": ["orders"]}
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.executescript("CREATE TABLE orders(id INTEGER PRIMARY KEY, status TEXT);"
                         "INSERT INTO orders VALUES(1,'confirmed');"
                         "CREATE TABLE private_data(n); INSERT INTO private_data VALUES(99);")
    server = create_server(load_config(save(use_skills=True)))
    yield server, server.gateway_runtime, root
    server.gateway_runtime.close()


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_same_client_add_change_disable_delete_and_policy(deployment, mode):
    server, runtime, root = deployment
    async with Client(server, mode=mode) as client:
        initial_tools = [tool.name for tool in await client.list_tools()]
        assert "reload_skills" in initial_tools
        original = (await client.call_tool("execute_query_skill", {"skill_name": "report", "params": {"n": 7}})).structured_content
        assert original["data"] == [{"n": 7}]
        write_query(root, sql="SELECT :n + 1 AS n")
        write_query(root, "new-report", "SELECT 99 AS n", params=False)
        # Files on disk are not implicitly activated by ordinary calls.
        old = (await client.call_tool("execute_query_skill", {"skill_name": "report", "params": {"n": 7}})).structured_content
        assert old["data"] == [{"n": 7}]
        reload = (await client.call_tool("reload_skills", {})).structured_content
        assert reload["success"] and reload["revision"] == 1
        assert reload["added"] == ["new-report"] and reload["changed"] == ["report"]
        detail = (await client.call_tool("get_skill_detail", {"skill_name": "new-report"})).structured_content
        assert detail["skill"]["name"] == "new-report"
        result = (await client.call_tool("execute_query_skill", {"skill_name": "report", "params": {"n": 7}})).structured_content
        assert result["data"] == [{"n": 8}]
        assert [tool.name for tool in await client.list_tools()] == initial_tools
        assert (await client.call_tool("reload_skills", {})).structured_content["revision"] == 1
        # Reloading definitions grants no access to a newly referenced table.
        write_query(root, "forbidden", "SELECT n FROM private_data", params=False)
        assert (await client.call_tool("reload_skills", {})).structured_content["success"]
        denied = (await client.call_tool("execute_query_skill", {"skill_name": "forbidden", "params": {}})).structured_content
        assert denied["success"] is False and denied["error_code"] == "table_access_denied"
        shutil.rmtree(root / "new-report")
        definition = root / "report" / "skill_def.md"
        definition.write_text(definition.read_text().replace("risk: low", "risk: low\nenabled: false"))
        removed = (await client.call_tool("reload_skills", {})).structured_content
        assert removed["removed"] == ["new-report", "report"]
        assert "report" not in runtime.catalog.get_skills_cache()


@pytest.mark.parametrize("fault,reason", [
    ("unsafe", "read_only_required"),
    ("metadata", "invalid_skill_definition"),
    ("missing_source", "query_source_unavailable"),
    ("empty", "empty_query_source"),
    ("missing_definition", "query_definition_unavailable"),
    ("type_change", "skill_type_change_requires_restart"),
    ("outside_source", "query_source_outside_skill"),
    ("missing_root", "skills_directory_unavailable"),
])
async def test_failed_reload_keeps_old_catalog_and_reports_safe_reason(deployment, tmp_path, fault, reason):
    server, runtime, root = deployment
    old = runtime.catalog
    source = root / "report" / "query.sql"
    definition = root / "report" / "skill_def.md"
    if fault == "unsafe": source.write_text("DELETE FROM orders")
    elif fault == "metadata": definition.write_text("invalid frontmatter")
    elif fault == "missing_source": source.unlink()
    elif fault == "empty": source.write_text("")
    elif fault == "missing_definition": definition.unlink()
    elif fault == "type_change": definition.write_text(definition.read_text().replace("type: query", "type: mutation").replace("query.sql", "mutation.py"))
    elif fault == "outside_source":
        source.unlink()
        target = tmp_path / "outside.sql"
        target.write_text("SELECT 99 AS n")
        source.symlink_to(target)
    elif fault == "missing_root": shutil.rmtree(root)
    async with Client(server) as client:
        rejected = (await client.call_tool("reload_skills", {})).structured_content
        assert rejected["success"] is False and rejected["reason"] == reason
        assert str(tmp_path) not in str(rejected)
        assert runtime.catalog is old and runtime.catalog_revision == 0
        result = (await client.call_tool("execute_query_skill", {"skill_name": "report", "params": {"n": 7}})).structured_content
        assert result["data"] == [{"n": 7}]


async def test_inflight_snapshot_and_serialized_reload(deployment):
    _, runtime, root = deployment
    before = runtime.catalog
    entered, published = asyncio.Event(), asyncio.Event()
    async def old_request():
        with runtime.catalog_snapshot():
            entered.set()
            await published.wait()
            assert runtime.catalog is before
            assert runtime.catalog.load_query("report")[0] == "SELECT :n AS n"
    task = asyncio.create_task(old_request())
    await entered.wait()
    write_query(root, sql="SELECT :n + 1 AS n")
    runtime.reload_skills()
    published.set()
    await task
    assert runtime.catalog is not before
    assert runtime.catalog.load_query("report")[0] == "SELECT :n + 1 AS n"
    runtime._reload_lock.acquire()
    try:
        with pytest.raises(SkillReloadError, match="reload_in_progress"):
            runtime.reload_skills()
    finally:
        runtime._reload_lock.release()


async def test_source_changed_during_validation_is_not_published(deployment, monkeypatch):
    _, runtime, root = deployment
    from sql_safety_executor.core import runtime as module
    original = module._validate_sql_template_startup_policy
    before = runtime.catalog
    def validate(owner, sql):
        decision = original(owner, sql)
        (root / "report" / "query.sql").write_text("SELECT 99 AS n")
        return decision
    monkeypatch.setattr(module, "_validate_sql_template_startup_policy", validate)
    with pytest.raises(SkillReloadError, match="files_changed_during_reload"):
        runtime.reload_skills()
    assert runtime.catalog is before


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_actual_inflight_mcp_call_keeps_original_snapshot(deployment, mode):
    from fastmcp.server.middleware import Middleware
    server, runtime, root = deployment
    entered, release = asyncio.Event(), asyncio.Event()
    old_catalog = runtime.catalog
    class HoldFirstQuery(Middleware):
        held = False
        async def on_call_tool(self, context, call_next):
            if context.message.name == "execute_query_skill" and not self.held:
                self.held = True
                assert runtime.catalog is old_catalog
                entered.set()
                await release.wait()
                assert runtime.catalog is old_catalog
            return await call_next(context)
    server.add_middleware(HoldFirstQuery())
    async with Client(server, mode=mode) as client:
        args = {"skill_name": "report", "params": {"n": 7}}
        inflight = asyncio.create_task(client.call_tool("execute_query_skill", args))
        await asyncio.wait_for(entered.wait(), timeout=5)
        try:
            write_query(root, sql="SELECT :n + 1 AS n")
            assert (await client.call_tool("reload_skills", {})).structured_content["success"]
        finally:
            release.set()
        assert (await inflight).structured_content["data"] == [{"n": 7}]
        assert (await client.call_tool("execute_query_skill", args)).structured_content["data"] == [{"n": 8}]


async def test_new_mutation_is_reported_without_import_and_query_params_update(deployment):
    server, runtime, root = deployment
    candidate = root / "new-mutation"
    candidate.mkdir()
    (candidate / "skill_def.md").write_text(
        "---\nname: new-mutation\ntype: mutation\nsource: mutation.py\n"
        "risk: medium\ndescription: Requires restart\nrequires_confirmation: true\nparams: {}\n---\n")
    (candidate / "mutation.py").write_text("raise RuntimeError('MUST NOT IMPORT')")
    source = root / "report" / "query.sql"
    definition = root / "report" / "skill_def.md"
    source.write_text("SELECT :other AS n")
    definition.write_text(definition.read_text().replace("  n:", "  other:"))
    async with Client(server) as client:
        result = (await client.call_tool("reload_skills", {})).structured_content
        assert result["success"] and result["ignored_new_mutations"] == ["new-mutation"]
        assert "new-mutation" not in runtime.catalog.get_skills_cache()
        detail = (await client.call_tool("get_skill_detail", {"skill_name": "report"})).structured_content
        assert "other" in detail["skill"]["params"] and "n" not in detail["skill"]["params"]
        assert (await client.call_tool("execute_query_skill", {
            "skill_name": "report", "params": {"other": 99}})).structured_content["data"] == [{"n": 99}]


async def test_mutation_python_and_pending_preview_are_not_reloaded(bundle, tmp_path):
    _, connections, settings, save = bundle
    root = tmp_path / "skills"
    root.mkdir()
    write_query(root)
    sample = Path(__file__).resolve().parents[1] / "skills" / "sample-update-order-status"
    shutil.copytree(sample, root / sample.name)
    connections["connections"]["demo"]["mutation"] = {"enabled": True, "skills": [sample.name]}
    settings["skills"]["directory"] = str(root)
    settings["skills"]["mutation"]["mrtr"]["enabled"] = False
    connections["connections"]["demo"]["read"] = {"mode": "all"}
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.executescript("CREATE TABLE orders(id INTEGER PRIMARY KEY,status TEXT); INSERT INTO orders VALUES(1,'confirmed');")
    server = create_server(load_config(save(use_skills=True)))
    runtime = server.gateway_runtime
    async with Client(server) as client:
        args = {"skill_name": sample.name, "params": {"order_id": 1, "new_status": "shipped"}, "confirm": False}
        preview = (await client.call_tool("execute_mutation_skill", args)).structured_content
        assert preview["success"] and preview["preview_token"]
        old_mutation = runtime.catalog.get_skills_cache()[sample.name]
        old_store = runtime.tokens
        assert len(old_store) == 1
        (root / sample.name / "mutation.py").write_text("raise RuntimeError('MUST NOT IMPORT')")
        (root / sample.name / "skill_def.md").write_text("MUTATION METADATA MUST STAY UNREAD")
        write_query(root, "new-report", "SELECT 99 AS n", params=False)
        result = (await client.call_tool("reload_skills", {})).structured_content
        assert result["success"] and result["preserved_mutations"] == [sample.name]
        assert runtime.catalog.get_skills_cache()[sample.name] is old_mutation
        assert runtime.tokens is old_store and len(old_store) == 1
        with sqlite3.connect(tmp_path / "db.sqlite") as db:
            assert db.execute("SELECT status FROM orders").fetchone() == ("confirmed",)
