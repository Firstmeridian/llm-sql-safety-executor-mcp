"""Same-client Mutation publication with independent committed-state checks."""

from pathlib import Path
import shutil
import sqlite3

from fastmcp import Client
from fastmcp.exceptions import ToolError
import pytest

from sql_safety_executor import create_server, load_config
from sql_safety_executor.skills.catalog import SkillReloadError
from tests.test_v38_config import bundle as bundle


def write_mutation(root, name="change-n", *, offset=0, kind="managed"):
    directory = root / name
    directory.mkdir(exist_ok=True)
    (directory / "skill_def.md").write_text(
        f"---\nname: {name}\ntype: mutation\nsource: mutation.py\nrisk: medium\n"
        "description: Change an isolated fixture row\nversion: '1.0'\n"
        "requires_confirmation: true\ndatabases: [sqlite]\ntables: [orders]\n"
        "params:\n  order_id: {type: int, required: true}\n"
        "  new_n: {type: int, required: true}\n---\n", encoding="utf-8")
    sql = f"UPDATE orders SET n=:new_n + {offset} WHERE id=:order_id AND n=:expected"
    body = '''
    def validate(self, params):
        return {"valid": True}

    def preview(self, params):
        rows = self.adapter.execute("SELECT n FROM orders WHERE id=:id", params={"id": params["order_id"]})
        return {"current_n": rows[0][0], "affected_rows_estimate": 1}

    def build_execution_binding(self, params, validation, preview):
        return {"expected": preview["current_n"]}
'''
    if kind == "managed":
        source = (
            "from sql_safety_executor.skills.mutation import ManagedMutationBase, ManagedMutationPlan, ManagedMutationValue\n"
            "class Mutation(ManagedMutationBase):\n"
            f"    managed_plan = ManagedMutationPlan(sql={sql!r}, parameters=(\n"
            "        ManagedMutationValue.from_params('new_n'),\n"
            "        ManagedMutationValue.from_params('order_id'),\n"
            "        ManagedMutationValue.from_binding('expected'),\n"
            "    ), expected_rowcount=1)\n" + body)
    else:
        source = (
            "from sql_safety_executor.skills.mutation import MutationBase\n"
            "class Mutation(MutationBase):\n" + body
            + "\n    def execute(self, params):\n        raise RuntimeError('binding required')\n"
            + "\n    def execute_with_binding(self, params, execution_binding):\n"
            + f"        return self.adapter.execute_write({sql!r}, {{**params, **execution_binding}}, expected_rowcount=1)\n")
    (directory / "mutation.py").write_text(source, encoding="utf-8")
    return directory


@pytest.fixture
def reload_deployment(bundle, tmp_path):
    _, connections, settings, save = bundle
    root = tmp_path / "skills"
    root.mkdir()
    settings["skills"]["directory"] = str(root)
    settings["skills"]["mutation"]["mrtr"]["enabled"] = False
    connections["connections"]["demo"]["read"] = {"mode": "all"}
    connections["connections"]["demo"]["mutation"] = {
        "enabled": True, "skills": ["change-n", "untouched", "added"]}
    query = root / "report"
    query.mkdir()
    (query / "skill_def.md").write_text(
        "---\nname: report\ntype: query\nsource: query.sql\nrisk: low\ndescription: Fixture report\nparams: {}\n---\n")
    (query / "query.sql").write_text("SELECT 7 AS n")

    def start(kind="managed"):
        write_mutation(root, kind=kind)
        write_mutation(root, "untouched", kind=kind)
        path = tmp_path / "db.sqlite"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, n INTEGER)")
            db.execute("INSERT INTO orders VALUES(1,7)")
        server = create_server(load_config(save(use_skills=True)))
        return server, server.gateway_runtime, root, path

    servers = []
    def deployment(kind="managed"):
        result = start(kind)
        servers.append(result[0])
        return result
    yield deployment
    for server in servers:
        server.gateway_runtime.close()


def observed(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT n FROM orders WHERE id=1").fetchone()[0]


async def prepare(client, name="change-n", new_n=8):
    return (await client.call_tool("execute_mutation_skill", {
        "skill_name": name, "params": {"order_id": 1, "new_n": new_n},
        "connection_id": "demo"})).structured_content


async def execute(client, proposal, name="change-n", new_n=8):
    return (await client.call_tool("execute_mutation_skill", {
        "skill_name": name, "params": {"order_id": 1, "new_n": new_n},
        "connection_id": "demo", "confirm": True,
        "preview_token": proposal["preview_token"]})).structured_content


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("kind", ["managed", "imperative"])
async def test_changed_source_invalidates_only_affected_preview(reload_deployment, mode, kind):
    server, runtime, root, path = reload_deployment(kind)
    old_meta = runtime.catalog.get_skills_cache()["change-n"]
    query_meta = runtime.catalog.get_skills_cache()["report"]
    async with Client(server, mode=mode) as client:
        old = await prepare(client)
        unchanged = await prepare(client, "untouched", new_n=9)
        write_mutation(root, offset=10, kind=kind)
        receipt = (await client.call_tool("reload_skills", {"skill_type": "mutation"})).structured_content
        assert receipt["success"] and receipt["changed"] == ["change-n"]
        assert receipt["invalidated_previews"] == 1 and len(runtime.tokens) == 1
        assert runtime.catalog.get_skills_cache()["report"] is query_meta
        assert runtime.catalog.get_skills_cache()["change-n"]._mutation_generation != old_meta._mutation_generation
        with pytest.raises(ToolError, match="preview_token"):
            await execute(client, old)
        assert observed(path) == 7
        result = await execute(client, unchanged, "untouched", new_n=9)
        assert result["success"] and observed(path) == 9
        fresh = await prepare(client)
        result = await execute(client, fresh)
        assert result["success"] and observed(path) == 18
        assert result["execution_outcome"] == ("committed" if kind == "managed" else "unknown")
        with pytest.raises(ToolError):
            await execute(client, fresh)
        assert observed(path) == 18


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_noop_addition_and_other_kind_do_not_invalidate(reload_deployment, mode):
    server, runtime, root, path = reload_deployment()
    before = runtime.catalog.get_skills_cache()["change-n"]
    async with Client(server, mode=mode) as client:
        old = await prepare(client)
        noop = (await client.call_tool("reload_skills", {"skill_type": "mutation"})).structured_content
        assert noop["revision"] == 0 and noop["invalidated_previews"] == 0
        assert runtime.catalog.get_skills_cache()["change-n"] is before
        write_mutation(root, "added")
        (root / "report/query.sql").write_text("SELECT 99 AS n")
        receipt = (await client.call_tool("reload_skills", {"skill_type": "mutation"})).structured_content
        assert receipt["added"] == ["added"] and receipt["invalidated_previews"] == 0
        assert runtime.catalog.load_query("report")[0] == "SELECT 7 AS n"
        detail = (await client.call_tool("get_skill_detail", {"skill_name": "added", "connection_id": "demo"})).structured_content
        assert detail["skill"]["name"] == "added"
        query = (await client.call_tool("reload_skills", {})).structured_content
        assert query["changed"] == ["report"] and query["invalidated_previews"] == 0
        assert runtime.catalog.get_skills_cache()["change-n"] is before
        assert (await execute(client, old))["success"] and observed(path) == 8


@pytest.mark.parametrize("fault", ["import", "plan", "missing", "metadata"])
async def test_invalid_candidate_preserves_catalog_and_token(reload_deployment, fault):
    server, runtime, root, path = reload_deployment()
    before = runtime.catalog
    async with Client(server) as client:
        old = await prepare(client)
        source = root / "change-n/mutation.py"
        if fault == "import": source.write_text("raise RuntimeError('PRIVATE PATH MUST NOT LEAK')")
        elif fault == "plan": source.write_text(source.read_text().replace("UPDATE orders SET n=", "SELECT n="))
        elif fault == "missing": source.unlink()
        else: (root / "change-n/skill_def.md").write_text("invalid")
        receipt = (await client.call_tool("reload_skills", {"skill_type": "mutation"})).structured_content
        assert not receipt["success"] and receipt["error_code"] == "mutation_reload_failed"
        assert "PRIVATE" not in str(receipt) and str(root) not in str(receipt)
        assert runtime.catalog is before and runtime.catalog_revision == 0
        assert (await execute(client, old))["success"] and observed(path) == 8


@pytest.mark.parametrize("removal", ["disabled", "deleted"])
async def test_remove_readd_and_revert_never_revive_old_proposals(reload_deployment, removal):
    server, runtime, root, path = reload_deployment()
    async with Client(server) as client:
        old = await prepare(client)
        first = runtime.catalog.get_skills_cache()["change-n"]._mutation_generation
        if removal == "disabled":
            p = root / "change-n/skill_def.md"
            p.write_text(p.read_text().replace("risk: medium", "risk: medium\nenabled: false"))
        else: shutil.rmtree(root / "change-n")
        receipt = (await client.call_tool("reload_skills", {"skill_type": "mutation"})).structured_content
        assert receipt["removed"] == ["change-n"] and receipt["invalidated_previews"] == 1
        write_mutation(root)
        runtime.reload_skills("mutation")
        assert runtime.catalog.get_skills_cache()["change-n"]._mutation_generation != first
        with pytest.raises(ToolError): await execute(client, old)
        current = await prepare(client)
        write_mutation(root, offset=10)
        runtime.reload_skills("mutation")
        write_mutation(root)
        runtime.reload_skills("mutation")
        with pytest.raises(ToolError): await execute(client, current)
        assert observed(path) == 7 and len(runtime.tokens) == 0


@pytest.mark.parametrize("skill_type,name", [("query", "report"), ("mutation", "change-n")])
async def test_definition_lost_after_precheck_keeps_catalog_and_proposal(
    reload_deployment, monkeypatch, skill_type, name
):
    from sql_safety_executor.skills.catalog import SkillCatalog

    server, runtime, root, path = reload_deployment()
    before = runtime.catalog
    original = SkillCatalog.discover
    definition = root / name / "skill_def.md"
    content = definition.read_bytes()

    def lost_during_scan(self, *args, **kwargs):
        # Active names are passed to the strict scan. Restore before returning
        # so a post-scan existence check alone cannot hide an incomplete candidate.
        definition.unlink()
        try:
            return original(self, *args, **kwargs)
        finally:
            definition.write_bytes(content)

    async with Client(server) as client:
        pending = await prepare(client)
        monkeypatch.setattr(SkillCatalog, "discover", lost_during_scan)
        receipt = (await client.call_tool("reload_skills", {"skill_type": skill_type})).structured_content
        assert not receipt["success"]
        assert receipt["reason"] == f"{skill_type}_definition_unavailable"
        assert runtime.catalog is before and runtime.catalog_revision == 0
        assert len(runtime.tokens) == 1
        assert (await execute(client, pending))["success"] and observed(path) == 8


@pytest.mark.parametrize("boundary", ["issue", "before_consume", "after_consume"])
@pytest.mark.parametrize("kind", ["managed", "imperative"])
async def test_publication_linearizes_proposal_and_execution(reload_deployment, monkeypatch, boundary, kind):
    from sql_safety_executor.core import mutations
    server, runtime, root, path = reload_deployment(kind)
    async with Client(server) as client:
        old = await prepare(client) if boundary != "issue" else None
        name = "_register_mutation_preview_token" if boundary == "issue" else "_consume_mutation_preview_token"
        original = getattr(mutations, name)
        receipts = []
        def interleave(*args, **kwargs):
            if boundary == "after_consume": result = original(*args, **kwargs)
            write_mutation(root, offset=10, kind=kind)
            receipts.append(runtime.reload_skills("mutation"))
            if boundary == "after_consume": return result
            return original(*args, **kwargs)
        monkeypatch.setattr(mutations, name, interleave)
        if boundary == "after_consume":
            result = await execute(client, old)
            assert result["success"] and observed(path) == 8
            assert receipts[0]["invalidated_previews"] == 0
        else:
            with pytest.raises(ToolError, match="definition changed"):
                if boundary == "issue": await prepare(client)
                else: await execute(client, old)
            assert observed(path) == 7
        assert len(runtime.tokens) == 0


async def test_generation_change_includes_metadata_and_disabled_mutation_does_not_import(reload_deployment):
    server, runtime, root, path = reload_deployment()
    async with Client(server) as client:
        old = await prepare(client)
        p = root / "change-n/skill_def.md"
        p.write_text(p.read_text().replace("description: Change", "description: Updated"))
        receipt = runtime.reload_skills("mutation")
        assert receipt["changed"] == ["change-n"] and receipt["invalidated_previews"] == 1
        with pytest.raises(ToolError): await execute(client, old)
        assert observed(path) == 7
    # Config is immutable: build a separate no-write runtime for disabled admission.
    from dataclasses import replace
    mutation_config = runtime.config.skills.mutation.model_copy(update={"enabled": False})
    cfg = replace(runtime.config, skills=runtime.config.skills.model_copy(update={"mutation": mutation_config}))
    (root / "change-n/mutation.py").write_text("raise AssertionError('MUST NOT IMPORT')")
    other = create_server(cfg)
    try:
        with pytest.raises(SkillReloadError, match="mutation_reload_disabled"):
            other.gateway_runtime.reload_skills("mutation")
    finally: other.gateway_runtime.close()
