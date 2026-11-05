"""Catalog-only mutation candidate discovery; no server or database calls."""

from dataclasses import replace
import hashlib
import os
from pathlib import Path
import py_compile
import sys

import pytest

from sql_safety_executor.database.relations import RelationReference
from sql_safety_executor.skills import catalog as catalog_module
from sql_safety_executor.skills.catalog import (
    SkillCatalog,
    SkillMetadata,
    SkillReloadError,
    _load_mutation_class,
    skill_signature,
)


def mutation_source(state="A", marker=None):
    sentinel = ""
    if marker is not None:
        sentinel = (
            "from pathlib import Path\n"
            f"marker = Path({str(marker)!r})\n"
            "marker.write_text((marker.read_text() if marker.exists() else '') + 'x')\n"
        )
    sql = f"UPDATE orders SET status = '{state}' WHERE id = :order_id"
    return (
        "from sql_safety_executor.skills.mutation import (\n"
        "    ManagedMutationBase, ManagedMutationPlan, ManagedMutationValue)\n"
        + sentinel
        + f"STATE = {state!r}\n"
        "class Mutation(ManagedMutationBase):\n"
        f"    managed_plan = ManagedMutationPlan({sql!r},\n"
        "        (ManagedMutationValue.from_params('order_id'),), 1)\n"
        "    def validate(self, params): return {'valid': True}\n"
        "    def preview(self, params): return {'state': STATE}\n"
    )


def write_skill(root, name="write-order", *, kind="mutation", source=None, enabled=True):
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    filename = "mutation.py" if kind == "mutation" else "query.sql"
    (directory / "skill_def.md").write_text(
        f"---\nname: {name}\ntype: {kind}\nsource: {filename}\n"
        "risk: medium\ndescription: A catalog candidate\n"
        f"enabled: {str(enabled).lower()}\n"
        "params:\n  order_id: {type: int, required: true}\n---\n",
        encoding="utf-8",
    )
    if source is None:
        source = mutation_source() if kind == "mutation" else "SELECT :order_id"
    path = directory / filename
    path.write_text(source, encoding="utf-8")
    return path


def state(meta):
    return meta._mutation_class(None, None).preview({})["state"]


def test_unchanged_reuses_entire_metadata_without_top_level_import(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    marker = tmp_path / "imports"
    write_skill(root, source=mutation_source(marker=marker))
    before = SkillCatalog().discover(root)
    old = before["write-order"]
    old._inferred_analysis[()] = object()
    old_class, old_plan, old_generation = (
        old._mutation_class, old._managed_mutation_plan, old._mutation_generation
    )

    def unexpected(*args, **kwargs):
        pytest.fail("Unchanged mutations must not import or rebuild their plans")

    monkeypatch.setattr(catalog_module, "_load_mutation_class", unexpected)
    monkeypatch.setattr(catalog_module, "_managed_plan_for_class", unexpected)
    candidate = SkillCatalog().discover(
        root, mutation_only=True, strict=True, reuse_mutations=before
    )

    assert candidate["write-order"] is old
    assert old._mutation_class is old_class
    assert old._managed_mutation_plan is old_plan
    assert old._mutation_generation == old_generation
    assert marker.read_text() == "x"


def test_same_length_same_mtime_change_bypasses_stale_pyc_and_isolates_globals(tmp_path):
    root = tmp_path / "skills"
    source = write_skill(root)
    pyc = Path(py_compile.compile(str(source), doraise=True))
    cached_bytes = pyc.read_bytes()
    before = SkillCatalog().discover(root)
    old = before["write-order"]
    info = source.stat()
    source.write_text(mutation_source("B"), encoding="utf-8")
    os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert source.stat().st_size == info.st_size
    assert source.stat().st_mtime_ns == info.st_mtime_ns

    new = SkillCatalog().discover(
        root, mutation_only=True, strict=True, reuse_mutations=before
    )["write-order"]

    assert state(old) == "A"
    assert state(new) == "B"
    assert new._mutation_class is not old._mutation_class
    assert new._mutation_class.__module__ != old._mutation_class.__module__
    assert old._mutation_class.__module__ not in sys.modules
    assert new._mutation_class.__module__ not in sys.modules
    assert new._managed_mutation_plan is not old._managed_mutation_plan
    assert "'A'" in old._managed_mutation_plan.sql
    assert "'B'" in new._managed_mutation_plan.sql
    assert new._mutation_source_digest == hashlib.sha256(source.read_bytes()).hexdigest()
    assert new._mutation_source_digest != old._mutation_source_digest
    assert new._mutation_generation != old._mutation_generation
    assert pyc.read_bytes() == cached_bytes


def test_generation_is_fresh_for_new_candidates_and_a_b_a_transitions(tmp_path):
    root = tmp_path / "skills"
    source = write_skill(root)
    first = SkillCatalog().discover(root)["write-order"]
    separate = SkillCatalog().discover(root)["write-order"]
    source.write_text(mutation_source("B"), encoding="utf-8")
    second = SkillCatalog().discover(
        root, strict=True, reuse_mutations={first.name: first}
    )[first.name]
    source.write_text(mutation_source("A"), encoding="utf-8")
    third = SkillCatalog().discover(
        root, strict=True, reuse_mutations={second.name: second}
    )[first.name]

    assert skill_signature(first) == skill_signature(separate) == skill_signature(third)
    assert skill_signature(first) != skill_signature(second)
    generations = {meta._mutation_generation for meta in (first, separate, second, third)}
    assert None not in generations and len(generations) == 4
    assert all(meta._mutation_generation != meta._mutation_source_digest
               for meta in (first, separate, second, third))
    assert [state(meta) for meta in (first, second, third)] == ["A", "B", "A"]


def test_changed_public_metadata_imports_fresh_candidate(tmp_path):
    root = tmp_path / "skills"
    marker = tmp_path / "imports"
    source = write_skill(root, source=mutation_source(marker=marker))
    before = SkillCatalog().discover(root)
    old = before["write-order"]
    definition = source.parent / "skill_def.md"
    definition.write_text(definition.read_text().replace("risk: medium", "risk: high"))
    new = SkillCatalog().discover(root, strict=True, reuse_mutations=before)[old.name]

    assert new is not old and new.risk == "high" and old.risk == "medium"
    assert new._mutation_source_digest == old._mutation_source_digest
    assert new._mutation_generation != old._mutation_generation
    assert marker.read_text() == "xx"


def test_signature_serializes_relations_and_ignores_other_internal_state():
    original = SkillMetadata(
        name="report", type="query", source="query.sql", risk="low", description="Report",
        params={"order_id": {"type": "int", "required": True}},
        relations=[RelationReference(name="orders", schema="main")],
        _sql_template="SELECT :order_id",
    )
    reordered = replace(original, params={"order_id": {"required": True, "type": "int"}})
    changed_internals = replace(
        reordered, _inferred_analysis={(): object()}, _mutation_class=object,
        _managed_mutation_plan=object(), _mutation_generation="another-generation",
    )

    signature = skill_signature(original)
    assert len(signature) == 64 and int(signature, 16) >= 0
    assert signature == skill_signature(reordered) == skill_signature(changed_internals)
    for change in (
        {"description": "Changed"}, {"requires_confirmation": True},
        {"connection_ids": ["other"]}, {"params": {}},
        {"relations": [RelationReference(name="orders", schema="other")]},
        {"_sql_template": "SELECT :order_id + 1"},
        {"_mutation_source_digest": "changed-source"},
    ):
        assert skill_signature(replace(original, **change)) != signature


@pytest.mark.parametrize(("replacement", "reason"), [
    ("def broken(\n", "invalid_mutation_module"),
    ("import nonexistent_catalog_reload_test_dependency\n", "invalid_mutation_module"),
    ("Mutation = object()\n", "invalid_mutation_module"),
    ("raise RuntimeError('SECRET SQL /private/source/path')\n", "invalid_mutation_module"),
    ("raise SystemExit('/private/source/path')\n", "invalid_mutation_module"),
    (mutation_source("B") + "    def run_execute(self, *args): return {}\n",
     "invalid_mutation_module"),
    (mutation_source("B").replace("UPDATE orders SET status = 'B'", "SELECT * FROM orders"),
     "invalid_managed_mutation_plan"),
    (mutation_source("B").replace("order_id", "undeclared_id"), "invalid_managed_mutation_plan"),
])
def test_invalid_candidate_keeps_caller_owned_objects_and_cache(tmp_path, replacement, reason):
    root = tmp_path / "skills"
    source = write_skill(root)
    catalog = SkillCatalog()
    before = catalog.discover(root)
    old = before["write-order"]
    signature, generation, plan = skill_signature(old), old._mutation_generation, old._managed_mutation_plan
    source.write_text(replacement, encoding="utf-8")

    with pytest.raises(SkillReloadError) as caught:
        catalog.discover(root, mutation_only=True, strict=True, reuse_mutations=before)

    assert caught.value.reason == reason
    assert caught.value.skill_name == old.name
    assert str(caught.value) == reason
    assert catalog.get_skills_cache() is before
    assert before[old.name] is old and state(old) == "A"
    assert skill_signature(old) == signature and old._mutation_generation == generation
    assert old._managed_mutation_plan is plan


@pytest.mark.parametrize(("fault", "reason"), [
    ("missing", "mutation_source_unavailable"),
    ("directory", "mutation_source_unavailable"),
    ("outside_source", "mutation_source_outside_skill"),
    ("outside_directory", "skill_directory_outside_root"),
    ("outside_definition", "definition_outside_skill"),
    ("invalid_filename", "invalid_skill_definition"),
    ("missing_source_field", "invalid_skill_definition"),
])
@pytest.mark.parametrize("load_mutations", [True, False])
def test_strict_source_and_path_faults_preserve_old_cache(tmp_path, fault, reason, load_mutations):
    root = tmp_path / "skills"
    source = write_skill(root)
    catalog = SkillCatalog()
    before = catalog.discover(root)
    definition = source.parent / "skill_def.md"
    if fault in {"missing", "directory", "outside_source"}:
        source.unlink()
        if fault == "directory":
            source.mkdir()
        elif fault == "outside_source":
            outside = tmp_path / "outside.py"
            outside.write_text("raise AssertionError('Outside code must not execute')")
            source.symlink_to(outside)
    elif fault == "outside_directory":
        moved = tmp_path / source.parent.name
        source.parent.rename(moved)
        source.parent.symlink_to(moved, target_is_directory=True)
    elif fault == "outside_definition":
        outside = tmp_path / "outside.md"
        definition.rename(outside)
        definition.symlink_to(outside)
    elif fault == "invalid_filename":
        definition.write_text(definition.read_text().replace("mutation.py", "../outside.py"))
    elif fault == "missing_source_field":
        definition.write_text(definition.read_text().replace("source: mutation.py\n", ""))

    with pytest.raises(SkillReloadError, match=f"^{reason}$"):
        catalog.discover(
            root, strict=True, mutation_only=True, reuse_mutations=before,
            load_mutations=load_mutations,
        )

    assert catalog.get_skills_cache() is before
    assert state(before["write-order"]) == "A"


@pytest.mark.parametrize("fault", ["missing", "outside", "invalid"])
def test_enabled_false_skips_source_validation_and_import(tmp_path, fault):
    root = tmp_path / "skills"
    source = write_skill(root)
    before = SkillCatalog().discover(root)
    definition = source.parent / "skill_def.md"
    definition.write_text(definition.read_text().replace("enabled: true", "enabled: false"))
    if fault == "missing":
        source.unlink()
    elif fault == "outside":
        outside = tmp_path / "outside.py"
        source.rename(outside)
        source.symlink_to(outside)
    else:
        source.write_text("raise AssertionError('Disabled source must not import')")

    assert SkillCatalog().discover(
        root, mutation_only=True, strict=True, reuse_mutations=before
    ) == {}
    assert state(before["write-order"]) == "A"


def test_mutation_only_skips_query_sources_and_honors_skip_names(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    write_skill(root, "unsafe-query", kind="query", source="DELETE FROM orders")
    missing = write_skill(root, "missing-query", kind="query")
    missing.unlink()
    outside_query = write_skill(root, "outside-query", kind="query", enabled=False)
    outside = tmp_path / "outside.sql"
    outside_query.rename(outside)
    outside_query.symlink_to(outside)
    preserved = write_skill(root, "preserved-query", kind="query")
    (preserved.parent / "skill_def.md").write_text("Invalid metadata must stay unread")
    catalog = SkillCatalog()

    def unexpected(sql):
        pytest.fail("Mutation-only discovery must not validate Query SQL")

    result = catalog.discover(
        root, query_validator=unexpected, mutation_only=True, strict=True,
        skip_names=frozenset({"preserved-query"}),
    )

    assert set(result) == {"write-order"}
    assert catalog.ignored_queries == {"unsafe-query", "missing-query", "outside-query"}
    assert catalog.ignored_mutations == set()


def test_query_only_still_skips_mutation_sources_and_resets_ignored_queries(tmp_path):
    root = tmp_path / "skills"
    source = write_skill(root)
    write_skill(root, "report", kind="query")
    catalog = SkillCatalog()
    catalog.discover(root, mutation_only=True, strict=True)
    assert catalog.ignored_queries == {"report"}
    source.unlink()

    result = catalog.discover(root, query_only=True, strict=True)

    assert set(result) == {"report"}
    assert catalog.ignored_mutations == {"write-order"}
    assert catalog.ignored_queries == set()


def test_scope_flags_are_mutually_exclusive(tmp_path):
    with pytest.raises(ValueError, match="mutually exclusive"):
        SkillCatalog().discover(tmp_path, query_only=True, mutation_only=True)


def test_loading_disabled_never_imports_or_reuses_an_executable_class(tmp_path):
    root = tmp_path / "skills"
    source = write_skill(root)
    before = SkillCatalog().discover(root)
    listed = SkillCatalog().discover(
        root, load_mutations=False, strict=True, reuse_mutations=before
    )["write-order"]
    assert listed._mutation_class is None and listed._managed_mutation_plan is None
    assert listed._mutation_source_digest == before[listed.name]._mutation_source_digest
    assert listed is not before[listed.name]

    source.write_text("raise AssertionError('Must not import when loading is disabled')")
    unloaded = SkillCatalog().discover(root, load_mutations=False, strict=True)
    assert unloaded[listed.name]._mutation_class is None
    with pytest.raises(SkillReloadError, match="^invalid_mutation_module$"):
        SkillCatalog().discover(root, load_mutations=True, strict=True, reuse_mutations=unloaded)


@pytest.mark.parametrize("operation", ["stat", "read_bytes"])
def test_unreadable_source_has_safe_strict_reason(tmp_path, monkeypatch, operation):
    source = write_skill(tmp_path)
    original = getattr(Path, operation)

    def unavailable(path, *args, **kwargs):
        if path == source:
            raise PermissionError(f"PRIVATE {path}")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, operation, unavailable)
    with pytest.raises(SkillReloadError, match="^mutation_source_unavailable$"):
        SkillCatalog().discover(tmp_path, strict=True)


@pytest.mark.parametrize(("fault", "reason"), [
    ("same_stat_source_edit", "files_changed_during_reload"),
    ("source_removed", "files_changed_during_reload"),
    ("definition_edit", "files_changed_during_reload"),
    ("new_directory", "directory_changed_during_reload"),
])
def test_changes_during_candidate_validation_are_rejected(tmp_path, monkeypatch, fault, reason):
    root = tmp_path / "skills"
    source = write_skill(root)
    catalog = SkillCatalog()
    before = catalog.discover(root)
    source.write_text(mutation_source("B"), encoding="utf-8")
    original = catalog_module._managed_plan_for_class

    def validate(*args, **kwargs):
        plan = original(*args, **kwargs)
        if fault == "same_stat_source_edit":
            info = source.stat()
            source.write_text(mutation_source("C"), encoding="utf-8")
            os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
        elif fault == "source_removed":
            source.unlink()
        elif fault == "definition_edit":
            definition = source.parent / "skill_def.md"
            definition.write_text(definition.read_text() + "Changed during validation\n")
        else:
            (root / "new-directory").mkdir()
        return plan

    monkeypatch.setattr(catalog_module, "_managed_plan_for_class", validate)
    with pytest.raises(SkillReloadError, match=f"^{reason}$"):
        catalog.discover(root, strict=True, mutation_only=True, reuse_mutations=before)
    assert catalog.get_skills_cache() is before
    assert state(before["write-order"]) == "A"


def test_reused_source_is_still_observed_until_discovery_finishes(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    reused_source = write_skill(root, "a-reused")
    later_source = write_skill(root, "z-changed")
    before = SkillCatalog().discover(root)
    later_source.write_text(mutation_source("B"), encoding="utf-8")
    original = catalog_module._managed_plan_for_class

    def validate(meta, *args, **kwargs):
        assert meta.name == "z-changed"
        plan = original(meta, *args, **kwargs)
        reused_source.write_text(mutation_source("C"), encoding="utf-8")
        return plan

    monkeypatch.setattr(catalog_module, "_managed_plan_for_class", validate)
    with pytest.raises(SkillReloadError, match="^files_changed_during_reload$") as caught:
        SkillCatalog().discover(root, strict=True, mutation_only=True, reuse_mutations=before)
    assert caught.value.skill_name == "a-reused"
    assert state(before["a-reused"]) == "A"


def test_loader_uses_provided_bytes_and_honors_python_encoding_cookie(tmp_path):
    source = tmp_path / "mutation.py"
    source.write_text("raise AssertionError('Must compile provided bytes')")
    snapshot = ("# coding: latin-1\n" + mutation_source("é")).encode("latin-1")

    mutation_class = _load_mutation_class("write-order", source, source_bytes=snapshot)

    assert mutation_class(None, None).preview({}) == {"state": "é"}


def test_non_strict_startup_keeps_skipping_invalid_mutation_sources(tmp_path):
    write_skill(tmp_path, "bad-module", source="Mutation = object()")
    missing = write_skill(tmp_path, "missing-source")
    missing.unlink()
    write_skill(tmp_path, "bad-plan", source=mutation_source().replace("UPDATE orders SET status = 'A'", "SELECT * FROM orders"))
    write_skill(tmp_path, "valid")

    assert set(SkillCatalog().discover(tmp_path)) == {"valid"}
