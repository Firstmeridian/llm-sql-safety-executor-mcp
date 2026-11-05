"""Publication distinguishes abnormal active entries from intentional deletion."""

import os
from pathlib import Path
import shutil

from fastmcp import Client
import pytest

from sql_safety_executor.skills.catalog import SkillReloadError
from tests.test_v38_config import bundle  # noqa: F401
from tests.test_mutation_skill_reload import (
    execute, observed, prepare, reload_deployment,  # noqa: F401
)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("skill_type,name", [("query", "report"), ("mutation", "change-n")])
@pytest.mark.parametrize("replacement", ["file", "dangling", "loop"])
async def test_abnormal_active_entry_keeps_catalog_and_preview(
    reload_deployment, mode, skill_type, name, replacement
):
    server, runtime, root, path = reload_deployment()
    async with Client(server, mode=mode) as client:
        proposal = await prepare(client)
        before = runtime.catalog
        entry = root / name
        parked = root.parent / "parked-skill"
        entry.rename(parked)
        if replacement == "file":
            entry.write_text("incomplete deployment")
        else:
            entry.symlink_to(name if replacement == "loop" else "absent-target",
                             target_is_directory=True)
        receipt = (await client.call_tool("reload_skills", {"skill_type": skill_type})).structured_content
        assert receipt["success"] is False
        assert receipt["reason"] == "skill_directory_unavailable"
        assert receipt["skill_name"] == name and str(root) not in str(receipt)
        assert runtime.catalog is before and runtime.catalog_revision == 0
        assert len(runtime.tokens) == 1 and observed(path) == 7
        # A rejected deployment leaves cached definitions and the old preview usable.
        report = (await client.call_tool("execute_query_skill", {
            "skill_name": "report", "params": {}, "connection_id": "demo",
        })).structured_content
        assert report["data"] == [{"n": 7}]
        assert (await execute(client, proposal))["success"] and observed(path) == 8


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("skill_type,name", [("query", "report"), ("mutation", "change-n")])
async def test_real_directory_deletion_remains_supported(
    reload_deployment, mode, skill_type, name
):
    server, runtime, root, path = reload_deployment()
    async with Client(server, mode=mode) as client:
        await prepare(client)
        shutil.rmtree(root / name)
        (root / "README.txt").write_text("Not a Skill directory")
        receipt = (await client.call_tool("reload_skills", {"skill_type": skill_type})).structured_content
        assert receipt["success"] and receipt["removed"] == [name]
        assert receipt["revision"] == 1
        assert receipt["invalidated_previews"] == int(skill_type == "mutation")
        assert name not in runtime.catalog.get_skills_cache()
        assert len(runtime.tokens) == int(skill_type == "query") and observed(path) == 7


@pytest.mark.parametrize("skill_type,name", [("query", "report"), ("mutation", "change-n")])
@pytest.mark.parametrize("restore_original", [False, True])
async def test_listed_active_directory_disappearing_during_scan_is_not_removal(
    reload_deployment, monkeypatch, skill_type, name, restore_original
):
    server, runtime, root, path = reload_deployment()
    async with Client(server) as client:
        await prepare(client)
        before = runtime.catalog
        entry, parked = root / name, root.parent / "parked-skill"
        iterdir = Path.iterdir
        calls = 0

        def scan(directory):
            nonlocal calls
            if directory != root:
                return iterdir(directory)
            calls += 1
            if calls == 2 and parked.exists():
                if restore_original:
                    parked.rename(entry)
                else:
                    shutil.copytree(parked, entry)
            entries = list(iterdir(directory))
            if calls == 1:
                entry.rename(parked)
            return iter(entries)

        monkeypatch.setattr(Path, "iterdir", scan)
        try:
            with pytest.raises(SkillReloadError, match="skill_directory_unavailable"):
                runtime.reload_skills(skill_type)
            assert runtime.catalog is before and runtime.catalog_revision == 0
            assert len(runtime.tokens) == 1 and observed(path) == 7
        finally:
            if parked.exists():
                if entry.exists():
                    shutil.rmtree(entry)
                parked.rename(entry)


@pytest.mark.parametrize("skill_type,name", [("query", "report"), ("mutation", "change-n")])
async def test_active_directory_replacement_with_unchanged_files_is_rejected(
    reload_deployment, monkeypatch, skill_type, name
):
    server, runtime, root, path = reload_deployment()
    async with Client(server) as client:
        proposal = await prepare(client)
        before = runtime.catalog
        entry = root / name
        replacement, parked = root.parent / "replacement", root.parent / "original"
        replacement.mkdir()
        files = sorted(entry.iterdir())
        assert files and all(item.is_file() for item in files)
        # Link before discovery: creating links changes ctime. The later directory
        # swap must leave every observed source-file identity and byte unchanged.
        for item in files:
            (replacement / item.name).hardlink_to(item)

        def file_snapshot():
            result = {}
            for item in files:
                info = item.stat()
                result[item.name] = (
                    info.st_dev, info.st_ino, info.st_size,
                    info.st_mtime_ns, info.st_ctime_ns, item.read_bytes(),
                )
            return result

        unchanged_files = file_snapshot()
        original_identity = entry.stat().st_dev, entry.stat().st_ino
        iterdir = Path.iterdir
        entries_before = sorted(iterdir(root))
        scans = 0

        def scan(directory):
            nonlocal scans
            entries = list(iterdir(directory))
            if directory == root:
                scans += 1
                if scans == 2:  # Sources have been read; final checks are next.
                    entry.rename(parked)
                    replacement.rename(entry)
                    assert file_snapshot() == unchanged_files
            return iter(entries)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "iterdir", scan)
            with pytest.raises(SkillReloadError, match="files_changed_during_reload") as error:
                runtime.reload_skills(skill_type)

        assert scans == 2 and error.value.skill_name == name
        assert sorted(iterdir(root)) == entries_before
        assert (entry.stat().st_dev, entry.stat().st_ino) != original_identity
        assert file_snapshot() == unchanged_files
        assert runtime.catalog is before and runtime.catalog_revision == 0
        assert len(runtime.tokens) == 1 and observed(path) == 7
        report = (await client.call_tool("execute_query_skill", {
            "skill_name": "report", "params": {}, "connection_id": "demo",
        })).structured_content
        assert report["data"] == [{"n": 7}]
        assert (await execute(client, proposal))["success"] and observed(path) == 8


@pytest.mark.skipif(os.name != "posix" or getattr(os, "geteuid", lambda: 0)() == 0,
                    reason="Requires ordinary POSIX search permissions")
@pytest.mark.parametrize("skill_type,preserved", [("query", "change-n"), ("mutation", "report")])
async def test_preserved_other_type_is_skipped_before_symlink_target_probe(
    reload_deployment, skill_type, preserved
):
    _, runtime, root, _ = reload_deployment()
    old_other = runtime.catalog.get_skills_cache()[preserved]
    private = root / "_vault" / "private"
    private.mkdir(parents=True)
    target = private / "definition"
    entry = root / preserved
    entry.rename(target)
    entry.symlink_to(target, target_is_directory=True)
    private.chmod(0)
    try:
        receipt = runtime.reload_skills(skill_type)
        assert receipt["success"] and receipt["revision"] == 0
        assert runtime.catalog.get_skills_cache()[preserved] is old_other
    finally:
        private.chmod(0o700)


@pytest.mark.parametrize("skill_type,name", [("query", "report"), ("mutation", "change-n")])
async def test_active_valid_internal_symlink_is_not_rejected(reload_deployment, skill_type, name):
    _, runtime, root, _ = reload_deployment()
    private = root / "_deployment"
    private.mkdir()
    entry, target = root / name, private / name
    entry.rename(target)
    entry.symlink_to(target, target_is_directory=True)
    receipt = runtime.reload_skills(skill_type)
    assert receipt["success"] and receipt["revision"] == 0
