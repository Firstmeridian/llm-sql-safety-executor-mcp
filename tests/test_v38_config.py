"""Production TOML contract, secrets, side-effect-free checks and instance isolation."""

from dataclasses import FrozenInstanceError
import json
import subprocess
import sys

import pytest
from pydantic import ValidationError
from sql_safety_executor import create_server, load_config
from sql_safety_executor.config.loader import ConfigError, explain_config
from tests.support import ROOT, write_toml


@pytest.fixture
def bundle(tmp_path):
    server = {
        "schema_version": 1,
        "files": {"connections": "connections.toml"},
        "server": {"default_connection": "demo"},
    }
    connections = {
        "schema_version": 1,
        "connections": {"demo": {"type": "sqlite", "sqlite": {"path": "db.sqlite"}}},
    }
    skills = {
        "schema_version": 1,
        "skills": {
            "enabled": True,
            "directory": str(ROOT / "skills"),
            "audit": {"path": str(tmp_path / "audit.jsonl")},
            "mutation": {
                "enabled": True,
                "allowed_connections": ["demo"],
                "mrtr": {"enabled": True},
            },
        },
    }

    def save(*, use_skills=False):
        if use_skills:
            server["files"]["skills"] = "skills.toml"
        for name, data in [
            ("server", server),
            ("connections", connections),
            ("skills", skills),
        ]:
            write_toml(tmp_path / (name + ".toml"), data)
        return tmp_path / "server.toml"

    return server, connections, skills, save


@pytest.mark.parametrize(
    "field,value",
    [
        ("typo", 1),
        ("tool_timeout_seconds", -1),
        ("tool_timeout_seconds", "30"),
        ("default_connection", "missing"),
    ],
)
def test_strict_server(bundle, field, value):
    main, _, _, save = bundle
    main["server"][field] = value
    with pytest.raises(ConfigError):
        load_config(save())


@pytest.mark.parametrize("version", [True, 1.0, 2, "1"])
def test_schema_version_strict(bundle, version):
    main, _, _, save = bundle
    main["schema_version"] = version
    with pytest.raises(ConfigError):
        load_config(save())


@pytest.mark.parametrize("source", ["value", "env", "file"])
def test_secret_sources_snapshot_and_redaction(bundle, tmp_path, monkeypatch, source):
    _, conns, _, save = bundle
    password = " leading secret\n"
    monkeypatch.setenv("TEST_SQL_SECRET", password)
    (tmp_path / "secret").write_bytes(password.encode())
    conns["connections"]["demo"] = {
        "type": "mysql",
        "mysql": {
            "host": "db",
            "user": "fixture",
            "database": "fixture",
            "password": {
                source: {"value": password, "env": "TEST_SQL_SECRET", "file": "secret"}[
                    source
                ]
            },
        },
    }
    config = load_config(save())
    monkeypatch.setenv("TEST_SQL_SECRET", "changed")
    (tmp_path / "secret").write_text("changed")
    assert config.connections["demo"].mysql_password.get_secret_value() == password
    assert password not in repr(config)
    assert password not in json.dumps(explain_config(config))
    assert config.sources["connections.demo.mysql.password"] == "secret:" + source


@pytest.mark.parametrize(
    "password",
    [
        {},
        {"value": ""},
        {"env": "ABSENT_SQL_SECRET"},
        {"file": "absent"},
        {"value": "PRIVATE", "env": "PRIVATE"},
        {"value": 123},
    ],
)
def test_secret_errors_do_not_echo_input(bundle, password):
    _, c, _, save = bundle
    c["connections"]["demo"] = {
        "type": "mysql",
        "mysql": {"host": "db", "user": "u", "database": "d", "password": password},
    }
    with pytest.raises(ConfigError) as exc:
        load_config(save())
    assert "PRIVATE" not in str(exc.value)


@pytest.mark.parametrize("content", [b"", b"a" * 65537, b"\xff"])
def test_invalid_secret_file(bundle, tmp_path, content):
    _, c, _, save = bundle
    (tmp_path / "secret").write_bytes(content)
    c["connections"]["demo"] = {
        "type": "mysql",
        "mysql": {
            "host": "db",
            "user": "u",
            "database": "d",
            "password": {"file": "secret"},
        },
    }
    with pytest.raises(ConfigError):
        load_config(save())


def test_paths_no_env_and_offline_commands(bundle, tmp_path, monkeypatch):
    main, _, _, save = bundle
    path = save()
    (tmp_path / ".env").write_text(
        "DB_TYPE=mysql\nFASTMCP_STRICT_INPUT_VALIDATION=false\n"
    )
    monkeypatch.setenv("DB_TYPE", "mysql")
    monkeypatch.chdir("/")
    cfg = load_config(path)
    assert cfg.connections["demo"].sqlite_database_path == str(tmp_path / "db.sqlite")
    assert not cfg.skills.enabled
    assert cfg.connections["demo"].policy.read_mode == "deny"
    for action in ["check", "explain"]:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "sql_safety_executor",
                "config",
                action,
                "--config",
                str(path),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    assert not (tmp_path / "db.sqlite").exists()
    assert not (tmp_path / "audit.jsonl").exists()


def test_config_is_immutable(bundle):
    *_, save = bundle
    cfg = load_config(save())
    with pytest.raises(TypeError):
        cfg.connections["x"] = cfg.connections["demo"]
    with pytest.raises(FrozenInstanceError):
        cfg.connections["demo"].db_type = "mysql"
    with pytest.raises(ValidationError):
        cfg.server.limits.result_rows = 5


@pytest.mark.parametrize(
    "mode,tables,union,valid",
    [
        ("deny", [], False, True),
        ("all", [], False, True),
        ("allowlist", [], False, True),
        ("all", ["orders"], False, False),
        ("deny", [], True, False),
        ("allowlist", [], True, False),
        ("allowlist", ["*"], False, False),
        ("allowlist", ["orders"], True, True),
        ("all", [], True, True),
    ],
)
def test_read_configuration_matrix(bundle, mode, tables, union, valid):
    _, c, _, save = bundle
    c["connections"]["demo"]["read"] = {
        "mode": mode,
        "tables": tables,
        "allow_union": union,
    }
    if valid:
        load_config(save())
    else:
        with pytest.raises(ConfigError):
            load_config(save())


@pytest.mark.parametrize(
    "field,value",
    [
        ("ttl_seconds", 0),
        ("ttl_seconds", 86401),
        ("max_entries", 0),
        ("max_entries", 100001),
        ("ttl_seconds", "30"),
    ],
)
def test_token_config_no_silent_fallback(bundle, field, value):
    _, _, sk, save = bundle
    sk["skills"]["mutation"]["preview"] = {field: value}
    with pytest.raises(ConfigError):
        load_config(save(use_skills=True))


def test_missing_explicit_files_default_and_duplicates(bundle):
    main, _, _, save = bundle
    path = save()
    path.with_name("connections.toml").unlink()
    with pytest.raises(ConfigError):
        load_config(path)
    save()
    main["files"]["skills"] = "missing.toml"
    with pytest.raises(ConfigError):
        load_config(save())
    main["files"].pop("skills")
    path = save()
    path.with_name("connections.toml").write_text(
        'schema_version=1\n[connections.demo]\ntype="sqlite"\ntype="mysql"\n'
    )
    with pytest.raises(ConfigError):
        load_config(path)


def test_timeout_inheritance_only(bundle):
    m, c, _, save = bundle
    m["defaults"] = {"timeouts": {"query_seconds": 50, "connect_seconds": 15}}
    c["connections"]["demo"]["timeouts"] = {"query_seconds": 7}
    cfg = load_config(save())
    db = cfg.connections["demo"]
    assert (db.query_timeout_seconds, db.connect_timeout_seconds) == (7, 15)
    assert (
        "defaults.timeouts.connect_seconds"
        in cfg.sources["connections.demo.timeouts.connect_seconds"]
    )


def test_disabled_skills_dont_import_and_external_enabled_directory(bundle, tmp_path):
    _, _, sk, save = bundle
    directory = tmp_path / "trusted-external"
    directory.mkdir()
    item = directory / "example"
    item.mkdir()
    (item / "skill_def.md").write_text(
        "---\nname: example\ntype: mutation\nsource: mutation.py\nrisk: high\n---\n"
    )
    (item / "mutation.py").write_text('raise RuntimeError("must not import")')
    sk["skills"] = {"enabled": False, "directory": str(directory)}
    cfg = load_config(save(use_skills=True))
    server = create_server(cfg)
    assert not server.gateway_runtime.catalog.get_skills_cache()
    server.gateway_runtime.close()
    sk["skills"]["enabled"] = True
    assert load_config(save(use_skills=True)).skills.directory == str(directory)


def test_package_import_has_no_framework_or_deployment_side_effects(tmp_path):
    code = 'import sys; import sql_safety_executor; import sql_safety_executor.config; import sql_safety_executor.skills; assert "fastmcp" not in sys.modules'
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "gate", ["skills", "global", "admission", "connection", "skill"]
)
def test_mutation_gate_matrix_rejects_without_opening_db(bundle, gate):
    import asyncio
    from sql_safety_executor.core.mutations import execute_mutation_skill
    from sql_safety_executor.core.types import NullContext, OperationError

    _, connections, skills, save = bundle
    target = connections["connections"]["demo"]
    target["mutation"] = {"enabled": True, "skills": ["sample-update-order-status"]}
    skills["skills"]["mutation"]["mrtr"]["enabled"] = False
    if gate == "skills":
        skills["skills"]["enabled"] = False
    if gate == "global":
        skills["skills"]["mutation"]["enabled"] = False
    if gate == "admission":
        skills["skills"]["mutation"]["allowed_connections"] = []
    if gate == "connection":
        target["mutation"]["enabled"] = False
    if gate == "skill":
        target["mutation"]["skills"] = []
    path = save(use_skills=True)
    server = create_server(load_config(path))
    try:
        with pytest.raises(OperationError):
            asyncio.run(
                execute_mutation_skill(
                    server.gateway_runtime,
                    "sample-update-order-status",
                    {"order_id": 1, "new_status": "confirmed"},
                    NullContext(),
                )
            )
        assert not path.with_name("db.sqlite").exists()
    finally:
        server.gateway_runtime.close()


def test_skill_snapshot_external_sources_and_symlink_boundary(bundle, tmp_path):
    _, connections, skills, save = bundle
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    definition = trusted / "static-read"
    definition.mkdir()
    (definition / "skill_def.md").write_text(
        "---\nname: static-read\ntype: query\nsource: query.sql\nrisk: low\n---\n"
    )
    (definition / "query.sql").write_text("SELECT 1 AS value")
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = outside / "escape"
    escaped.mkdir()
    (escaped / "skill_def.md").write_text(
        "---\nname: escape\ntype: query\nsource: query.sql\nrisk: low\n---\n"
    )
    (escaped / "query.sql").write_text("SELECT 2")
    (trusted / "escape").symlink_to(escaped, target_is_directory=True)
    skills["skills"] = {
        "enabled": True,
        "directory": str(trusted),
        "audit": {"path": str(tmp_path / "audit.jsonl")},
    }
    path = save(use_skills=True)
    server = create_server(load_config(path))
    try:
        assert set(server.gateway_runtime.catalog.get_skills_cache()) == {"static-read"}
        (definition / "query.sql").write_text("DROP TABLE orders")
        assert (
            server.gateway_runtime.catalog.load_query("static-read")[0]
            == "SELECT 1 AS value"
        )
    finally:
        server.gateway_runtime.close()


def test_missing_prompt_fails_and_initialization_cleans_up(bundle, monkeypatch):
    from sql_safety_executor.core.runtime import GatewayRuntime
    from sql_safety_executor.prompts import render

    *_, save = bundle
    closed = []
    original = GatewayRuntime.close

    def close(self):
        closed.append(self)
        original(self)

    monkeypatch.setattr(GatewayRuntime, "close", close)
    original_text = render.text

    def missing(name):
        if name == "assistant.md":
            raise FileNotFoundError("missing packaged prompt")
        return original_text(name)

    monkeypatch.setattr(render, "text", missing)
    with pytest.raises(FileNotFoundError):
        create_server(load_config(save()))
    assert len(closed) == 1 and not closed[0].registry._adapters
