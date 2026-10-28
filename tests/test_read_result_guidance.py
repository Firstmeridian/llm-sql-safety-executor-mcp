"""Result rules survive independent tool visibility; not model-behavior proofs."""
import pytest
from fastmcp import Client

from sql_safety_executor import create_server, load_config
from sql_safety_executor.prompts import render
from tests.test_v38_config import bundle as bundle


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("skills_on", [False, True])
async def test_each_read_tool_carries_fetched_and_truncated_result_rules(
    bundle, tmp_path, mode, skills_on,
):
    _, _, skills, save = bundle
    empty = tmp_path / "empty-skills"
    empty.mkdir()
    skills["skills"]["directory"] = str(empty)
    server = create_server(load_config(save(use_skills=skills_on)))
    try:
        async with Client(server, mode=mode) as client:
            descriptions = {t.name: t.description or "" for t in await client.list_tools()}
        assert ("execute_query_skill" in descriptions) is skills_on
        for name in ("query", "sample", *(["execute_query_skill"] if skills_on else [])):
            # Each one must retain its own rules if the Host hides other tools.
            assert render.text("read_results.md") in descriptions[name]
            assert "not all database matches" in " ".join(descriptions[name].split())
            assert "not no matches" in descriptions[name]
            assert "currency or measurement units supported by the task" in descriptions[name]
            assert "without guessing a unit" in descriptions[name]
            assert len(descriptions[name]) < 1800
        assert not (tmp_path / "db.sqlite").exists()
    finally:
        server.gateway_runtime.close()


def test_missing_read_rules_fail_registration(bundle, monkeypatch):
    _, _, _, save = bundle
    original = render.text

    def missing(name):
        if name == "read_results.md":
            raise FileNotFoundError(name)
        return original(name)

    monkeypatch.setattr(render, "text", missing)
    with pytest.raises(FileNotFoundError, match="read_results.md"):
        create_server(load_config(save()))
