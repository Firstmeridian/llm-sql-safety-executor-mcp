"""SQLite comment semantics survive query-Skill startup and target readiness."""
from dataclasses import replace

import pytest
from fastmcp import Client

from tests.test_managed_parser_v382 import managed_server as managed_server
from tests.test_v38_config import bundle as bundle


@pytest.mark.parametrize('mode', ['auto', 'legacy'])
async def test_sqlite_hint_shaped_query_skill_discovery_detail_readiness_execute(managed_server, tmp_path, mode):
    directory = tmp_path / 'skills' / 'comment-read'
    directory.mkdir()
    (directory / 'skill_def.md').write_text(
        '---\nname: comment-read\ntype: query\nsource: query.sql\nrisk: low\n'
        'description: SQLite comments are whitespace\ndatabases: [sqlite]\n'
        'tables: [main.orders]\nparams: {}\n---\n'
    )
    sql = "SELECT /*+ SET_VAR(sql_mode='ANSI_QUOTES') SLEEP(0) */ n FROM main.orders"
    (directory / 'query.sql').write_text(sql)
    server = managed_server()
    runtime = server.gateway_runtime
    runtime.config = replace(runtime.config, skills=runtime.config.skills.model_copy(update={
        'readiness': runtime.config.skills.readiness.model_copy(update={'check_schema': True}),
    }))
    assert 'comment-read' in runtime.catalog.get_skills_cache()
    async with Client(server, mode=mode) as client:
        listing = (await client.call_tool('list_skills', {'search': 'comment-read', 'detail_level': 'full'})).structured_content
        assert [value['name'] for value in listing['skills']] == ['comment-read']
        state = listing['skills'][0]
        assert state['executable'] and state['schema_ready'] and state['schema_check_available']
        assert state['missing_tables'] == state['unverified_tables'] == []
        detail = (await client.call_tool('get_skill_detail', {'skill_name': 'comment-read', 'detail_level': 'execution'})).structured_content
        assert detail['skill']['executable']
        raw = (await client.call_tool('query', {'sql': sql})).structured_content
        executed = (await client.call_tool('execute_query_skill', {'skill_name': 'comment-read', 'params': {}})).structured_content
        assert raw['success'] and executed['success']
        assert raw['data'] == executed['data'] == [{'n': 7}]
        assert raw['query'] == sql
