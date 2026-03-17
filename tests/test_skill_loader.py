"""
Tests for skill_loader.py — Skill Discovery, Loading, and Validation

Covers:
- skill_def.md frontmatter parsing (valid + malformed)
- Skill name validation (regex + path traversal)
- Parameter validation (types, ranges, enums, required/optional)
- Query SQL loading from cache (not disk)
- Mutation module loading (success + missing class + import error)
- discover() behavior (disabled skills, missing dirs, unsafe SQL)
- generate_skills_md()
- related_skills warning

Usage:
    pytest tests/test_skill_loader.py -v
"""

import os
import sys
import pytest
import logging
from pathlib import Path
from unittest.mock import patch

# Add project root and _lib to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "_lib"))


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(autouse=True)
def reset_skill_cache():
    """Reset the module-level skill cache before each test."""
    import skill_loader
    skill_loader._skills_cache = {}
    skill_loader._skills_dir = None
    yield
    skill_loader._skills_cache = {}
    skill_loader._skills_dir = None


@pytest.fixture
def skills_dir(tmp_path):
    """Create a temporary skills directory with sample skills."""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()

    # Create a valid query skill
    q_dir = skill_dir / "test-query"
    q_dir.mkdir()
    (q_dir / "skill_def.md").write_text(
        "---\n"
        "name: test-query\n"
        "type: query\n"
        "source: query.sql\n"
        "risk: low\n"
        "description: A test query skill\n"
        "triggers:\n"
        "  - test query\n"
        "  - testing\n"
        "params:\n"
        "  year: {type: int, required: true, min: 2000, max: 2100}\n"
        "  limit: {type: int, required: false, min: 1, max: 1000}\n"
        "category: testing\n"
        "---\n\n"
        "## Usage\nJust a test skill.\n",
        encoding="utf-8",
    )
    (q_dir / "query.sql").write_text(
        "SELECT * FROM orders WHERE YEAR(order_date) = :year LIMIT :limit",
        encoding="utf-8",
    )

    # Create a valid mutation skill
    m_dir = skill_dir / "test-mutation"
    m_dir.mkdir()
    (m_dir / "skill_def.md").write_text(
        "---\n"
        "name: test-mutation\n"
        "type: mutation\n"
        "source: mutation.py\n"
        "risk: medium\n"
        "description: A test mutation skill\n"
        "requires_confirmation: true\n"
        "idempotent: false\n"
        "params:\n"
        "  order_id: {type: int, required: true}\n"
        "  new_status: {type: str, required: true, enum: [pending, shipped]}\n"
        "category: testing\n"
        "related_skills:\n"
        "  - test-query\n"
        "---\n\n"
        "## Workflow\nTest mutation.\n",
        encoding="utf-8",
    )
    (m_dir / "mutation.py").write_text(
        "from mutation_base import MutationBase\n\n"
        "class Mutation(MutationBase):\n"
        "    def validate(self, params): return {'valid': True}\n"
        "    def preview(self, params): return {'preview_sql': 'UPDATE ...'}\n"
        "    def execute(self, params):\n"
        "        return self.adapter.execute_write(\n"
        "            'UPDATE orders SET status = :new_status WHERE id = :order_id',\n"
        "            params=params,\n"
        "        )\n",
        encoding="utf-8",
    )

    return skill_dir


@pytest.fixture
def discovered_skills(skills_dir):
    """Run discover() and return the results."""
    from skill_loader import discover
    return discover(skills_dir)


# =============================================================================
# test_validate_name_valid (#24)
# =============================================================================

class TestValidateName:
    """Tests for validate_name() — skill name regex validation."""

    def test_valid_names(self):
        """Valid names pass regex validation."""
        from skill_loader import validate_name

        valid_names = [
            "my-skill-1",
            "report2",
            "a",
            "123",
            "sales-report-2024",
            "x" * 64,
        ]
        for name in valid_names:
            validate_name(name)  # Should not raise

    def test_path_traversal_rejected(self):
        """#5: Path traversal attempts are rejected."""
        from skill_loader import validate_name

        with pytest.raises(ValueError, match="Invalid skill name"):
            validate_name("../../../etc/passwd")

    def test_uppercase_rejected(self):
        from skill_loader import validate_name

        with pytest.raises(ValueError, match="Invalid skill name"):
            validate_name("MySkill")

    def test_underscore_rejected(self):
        from skill_loader import validate_name

        with pytest.raises(ValueError, match="Invalid skill name"):
            validate_name("my_skill")

    def test_empty_rejected(self):
        from skill_loader import validate_name

        with pytest.raises(ValueError):
            validate_name("")

    def test_too_long_rejected(self):
        from skill_loader import validate_name

        with pytest.raises(ValueError):
            validate_name("a" * 65)

    def test_starts_with_hyphen_rejected(self):
        from skill_loader import validate_name

        with pytest.raises(ValueError, match="Invalid skill name"):
            validate_name("-bad-name")

    def test_slash_rejected(self):
        from skill_loader import validate_name

        with pytest.raises(ValueError, match="Invalid skill name"):
            validate_name("skill/name")

    def test_backslash_rejected(self):
        from skill_loader import validate_name

        with pytest.raises(ValueError, match="Invalid skill name"):
            validate_name("skill\\name")


# =============================================================================
# test_load_skill_success (#3) + test_load_query_returns_cached_sql (#28)
# =============================================================================

class TestLoadQuery:
    """Tests for load_query() — SQL template loading from cache."""

    def test_load_skill_success(self, discovered_skills):
        """#3: Successful frontmatter parse + query.sql load."""
        from skill_loader import load_query

        sql, params = load_query("test-query")
        assert "SELECT" in sql
        assert "orders" in sql
        assert "year" in params
        assert params["year"]["type"] == "int"

    def test_load_query_returns_cached_sql(self, skills_dir, discovered_skills):
        """#28: load_query() returns cached SQL, not from disk."""
        from skill_loader import load_query

        # Modify the file on disk — should not affect load_query()
        (skills_dir / "test-query" / "query.sql").write_text(
            "SELECT 'tampered' AS result",
            encoding="utf-8",
        )

        sql, _ = load_query("test-query")
        # Should still return original cached SQL, not the tampered version
        assert "tampered" not in sql
        assert "orders" in sql

    def test_load_skill_not_found(self, discovered_skills):
        """#4: Non-existent skill returns error."""
        from skill_loader import load_query

        with pytest.raises(FileNotFoundError, match="not found"):
            load_query("nonexistent-skill")

    def test_query_skill_type_mismatch(self, discovered_skills):
        """#22: Calling load_query on a mutation skill raises TypeError."""
        from skill_loader import load_query

        with pytest.raises(TypeError, match="mutation"):
            load_query("test-mutation")


# =============================================================================
# test_validate_params_valid (#6) + test_validate_params_invalid (#7) +
# test_no_params_skill (#29)
# =============================================================================

class TestValidateParams:
    """Tests for validate_params() — parameter schema validation."""

    def test_validate_params_valid(self):
        """#6: Valid parameters pass schema validation."""
        from skill_loader import validate_params

        schema = {
            "year": {"type": "int", "required": True, "min": 2000, "max": 2100},
            "month": {"type": "int", "required": True, "min": 1, "max": 12},
        }
        result = validate_params({"year": 2024, "month": 6}, schema)
        assert result == {"year": 2024, "month": 6}

    def test_validate_params_missing_required(self):
        """#7: Missing required parameter raises ValueError."""
        from skill_loader import validate_params

        schema = {"year": {"type": "int", "required": True}}
        with pytest.raises(ValueError, match="Missing required"):
            validate_params({}, schema)

    def test_validate_params_wrong_type(self):
        """#7: Wrong type raises TypeError."""
        from skill_loader import validate_params

        schema = {"year": {"type": "int", "required": True}}
        with pytest.raises(TypeError, match="expected type"):
            validate_params({"year": "not-a-number"}, schema)

    def test_validate_params_out_of_range(self):
        """#7: Out-of-range value raises ValueError."""
        from skill_loader import validate_params

        schema = {"month": {"type": "int", "required": True, "min": 1, "max": 12}}
        with pytest.raises(ValueError, match="exceeds maximum"):
            validate_params({"month": 13}, schema)

    def test_validate_params_below_min(self):
        from skill_loader import validate_params

        schema = {"month": {"type": "int", "required": True, "min": 1, "max": 12}}
        with pytest.raises(ValueError, match="below minimum"):
            validate_params({"month": 0}, schema)

    def test_validate_params_invalid_enum(self):
        """#7: Non-enum value raises ValueError."""
        from skill_loader import validate_params

        schema = {
            "status": {
                "type": "str",
                "required": True,
                "enum": ["pending", "shipped"],
            }
        }
        with pytest.raises(ValueError, match="not one of"):
            validate_params({"status": "invalid"}, schema)

    def test_validate_params_valid_enum(self):
        from skill_loader import validate_params

        schema = {
            "status": {
                "type": "str",
                "required": True,
                "enum": ["pending", "shipped"],
            }
        }
        result = validate_params({"status": "shipped"}, schema)
        assert result == {"status": "shipped"}

    def test_no_params_skill(self):
        """#29: Skill with no params field validates empty dict."""
        from skill_loader import validate_params

        result = validate_params({}, {})
        assert result == {}

    def test_validate_params_type_coercion(self):
        """String '42' is coerced to int 42."""
        from skill_loader import validate_params

        schema = {"year": {"type": "int", "required": True}}
        result = validate_params({"year": "2024"}, schema)
        assert result == {"year": 2024}
        assert isinstance(result["year"], int)

    def test_validate_params_optional_missing(self):
        """Optional parameter not provided is silently skipped."""
        from skill_loader import validate_params

        schema = {
            "year": {"type": "int", "required": True},
            "limit": {"type": "int", "required": False},
        }
        result = validate_params({"year": 2024}, schema)
        assert result == {"year": 2024}

    def test_validate_params_rejects_extra_params(self):
        """P2#2: Extra parameters not defined in schema are rejected."""
        from skill_loader import validate_params

        schema = {
            "year": {"type": "int", "required": True},
            "month": {"type": "int", "required": True},
        }
        with pytest.raises(ValueError, match="Unexpected parameter"):
            validate_params(
                {"year": 2024, "month": 6, "malicious_key": "drop table"},
                schema,
            )

    def test_validate_params_rejects_multiple_extra(self):
        """Multiple extra parameters are reported."""
        from skill_loader import validate_params

        schema = {"year": {"type": "int", "required": True}}
        with pytest.raises(ValueError, match="Unexpected parameter"):
            validate_params(
                {"year": 2024, "extra1": "a", "extra2": "b"},
                schema,
            )


# =============================================================================
# test_discover / test_malformed_skill_md (#20) / test_skill_enabled_false (#14) /
# test_discover_rejects_unsafe_sql (#26) / test_skills_dir_not_found (#23)
# =============================================================================

class TestDiscover:
    """Tests for discover() — skill discovery and validation."""

    def test_discover_finds_skills(self, skills_dir):
        """discover() finds and loads valid skills."""
        from skill_loader import discover

        skills = discover(skills_dir)
        assert "test-query" in skills
        assert "test-mutation" in skills
        assert skills["test-query"].type == "query"
        assert skills["test-mutation"].type == "mutation"

    def test_skill_enabled_false_skipped(self, tmp_path):
        """#14: enabled: false skill is not in results."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        q = sd / "disabled-skill"
        q.mkdir()
        (q / "skill_def.md").write_text(
            "---\n"
            "name: disabled-skill\n"
            "type: query\n"
            "source: query.sql\n"
            "risk: low\n"
            "description: Disabled\n"
            "enabled: false\n"
            "---\n\nDisabled.\n",
            encoding="utf-8",
        )
        (q / "query.sql").write_text("SELECT 1", encoding="utf-8")

        skills = discover(sd)
        assert "disabled-skill" not in skills

    def test_malformed_skill_md(self, tmp_path):
        """#20: Malformed YAML frontmatter is skipped with error."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        q = sd / "bad-skill"
        q.mkdir()
        (q / "skill_def.md").write_text(
            "---\n"
            "name: bad-skill\n"
            "invalid: yaml: [[\n"
            "---\n\nBroken.\n",
            encoding="utf-8",
        )

        skills = discover(sd)
        assert "bad-skill" not in skills

    def test_malformed_missing_required_field(self, tmp_path):
        """#20: Missing required field (type) is skipped."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        q = sd / "no-type"
        q.mkdir()
        (q / "skill_def.md").write_text(
            "---\n"
            "name: no-type\n"
            "risk: low\n"
            "description: Missing type\n"
            "---\n\nNo type.\n",
            encoding="utf-8",
        )

        skills = discover(sd)
        assert "no-type" not in skills

    def test_discover_rejects_unsafe_sql(self, tmp_path):
        """#26: query.sql with DROP TABLE is rejected at startup."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        q = sd / "bad-query"
        q.mkdir()
        (q / "skill_def.md").write_text(
            "---\n"
            "name: bad-query\n"
            "type: query\n"
            "source: query.sql\n"
            "risk: low\n"
            "description: Unsafe SQL\n"
            "---\n\nBad.\n",
            encoding="utf-8",
        )
        (q / "query.sql").write_text(
            "DROP TABLE users; SELECT 1",
            encoding="utf-8",
        )

        skills = discover(sd)
        assert "bad-query" not in skills

    def test_skills_dir_not_found(self, tmp_path):
        """#23: Non-existent skills dir returns empty, no crash."""
        from skill_loader import discover

        skills = discover(tmp_path / "nonexistent")
        assert skills == {}

    def test_related_skills_warning(self, tmp_path, caplog):
        """#16: related_skills referencing non-existent skill logs warning."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        q = sd / "lonely-skill"
        q.mkdir()
        (q / "skill_def.md").write_text(
            "---\n"
            "name: lonely-skill\n"
            "type: query\n"
            "source: query.sql\n"
            "risk: low\n"
            "description: Has dangling reference\n"
            "related_skills:\n"
            "  - nonexistent-skill\n"
            "---\n\nLonely.\n",
            encoding="utf-8",
        )
        (q / "query.sql").write_text("SELECT 1", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            skills = discover(sd)

        assert "lonely-skill" in skills
        assert any("nonexistent-skill" in r.message for r in caplog.records)

    def test_triggers_in_list_skills(self, discovered_skills):
        """#15: Skills have triggers in metadata."""
        meta = discovered_skills["test-query"]
        assert "test query" in meta.triggers
        assert "testing" in meta.triggers


# =============================================================================
# test_generate_skills_md (#25)
# =============================================================================

class TestGenerateSkillsMd:
    """Tests for generate_skills_md()."""

    def test_generate_skills_md(self, skills_dir, discovered_skills):
        """#25: SKILLS.md contains all enabled skill names and descriptions."""
        from skill_loader import generate_skills_md

        output = skills_dir / "SKILLS.md"
        generate_skills_md(discovered_skills, output)

        content = output.read_text(encoding="utf-8")
        assert "test-query" in content
        assert "test-mutation" in content
        assert "A test query skill" in content


# =============================================================================
# test_mutation_missing_mutation_class (#21) +
# test_mutation_import_error (#30)
# =============================================================================

class TestLoadMutation:
    """Tests for load_mutation() — cached module instantiation."""

    def test_mutation_missing_mutation_class(self, tmp_path):
        """#21: mutation.py without Mutation class — skill excluded at discover()."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        m = sd / "no-class"
        m.mkdir()
        (m / "skill_def.md").write_text(
            "---\n"
            "name: no-class\n"
            "type: mutation\n"
            "source: mutation.py\n"
            "risk: low\n"
            "description: No Mutation class\n"
            "---\n\nBad.\n",
            encoding="utf-8",
        )
        (m / "mutation.py").write_text(
            "# No Mutation class here\nfoo = 42\n",
            encoding="utf-8",
        )

        skills = discover(sd)
        # Skill excluded from cache because _load_mutation_class() failed
        assert "no-class" not in skills

    def test_mutation_import_error(self, tmp_path):
        """#30: mutation.py with import error — skill excluded at discover()."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        m = sd / "bad-import"
        m.mkdir()
        (m / "skill_def.md").write_text(
            "---\n"
            "name: bad-import\n"
            "type: mutation\n"
            "source: mutation.py\n"
            "risk: low\n"
            "description: Bad import\n"
            "---\n\nBroken.\n",
            encoding="utf-8",
        )
        (m / "mutation.py").write_text(
            "import completely_nonexistent_module_12345\n",
            encoding="utf-8",
        )

        skills = discover(sd)
        # Skill excluded from cache because _load_mutation_class() failed
        assert "bad-import" not in skills

    def test_load_mutation_type_mismatch(self, discovered_skills):
        """Calling load_mutation on a query skill raises TypeError."""
        from skill_loader import load_mutation

        with pytest.raises(TypeError, match="query"):
            load_mutation("test-query", None, None)

    def test_mutation_class_cached_at_discover(self, skills_dir):
        """P2#1: Mutation class is pre-loaded and cached by discover()."""
        from skill_loader import discover, get_skills_cache

        discover(skills_dir)
        cache = get_skills_cache()
        meta = cache["test-mutation"]
        assert meta._mutation_class is not None
        assert meta._mutation_class.__name__ == "Mutation"

    def test_load_mutation_uses_cached_class(self, discovered_skills):
        """P2#1: load_mutation() instantiates from cache, no disk I/O."""
        from skill_loader import load_mutation
        from unittest.mock import MagicMock

        mock_adapter = MagicMock()
        mock_logger = MagicMock()
        mutation = load_mutation("test-mutation", mock_adapter, mock_logger)
        assert mutation.adapter is mock_adapter
        assert mutation.logger is mock_logger


# =============================================================================
# TestSourceField — Explicit source declaration validation
# =============================================================================

class TestSourceField:
    """Tests for the mandatory 'source' field in skill_def.md.

    The 'source' field explicitly declares the execution file associated
    with a skill, following the Explicit Configuration principle.
    """

    def test_source_missing_rejected(self, tmp_path):
        """skill_def.md without 'source' field is rejected."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        q = sd / "no-source"
        q.mkdir()
        (q / "skill_def.md").write_text(
            "---\n"
            "name: no-source\n"
            "type: query\n"
            "risk: low\n"
            "description: Missing source field\n"
            "---\n\nNo source.\n",
            encoding="utf-8",
        )
        (q / "query.sql").write_text("SELECT 1", encoding="utf-8")

        skills = discover(sd)
        assert "no-source" not in skills

    def test_source_path_traversal_rejected(self, tmp_path):
        """source: ../etc/passwd is rejected (path traversal prevention)."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        q = sd / "traversal"
        q.mkdir()
        (q / "skill_def.md").write_text(
            "---\n"
            "name: traversal\n"
            "type: query\n"
            "source: ../etc/passwd\n"
            "risk: low\n"
            "description: Path traversal attempt\n"
            "---\n\nBad.\n",
            encoding="utf-8",
        )

        skills = discover(sd)
        assert "traversal" not in skills

    def test_source_backslash_traversal_rejected(self, tmp_path):
        """source with backslash path separator is rejected."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        q = sd / "backslash"
        q.mkdir()
        (q / "skill_def.md").write_text(
            "---\n"
            "name: backslash\n"
            "type: query\n"
            "source: '..\\\\secret.sql'\n"
            "risk: low\n"
            "description: Backslash traversal attempt\n"
            "---\n\nBad.\n",
            encoding="utf-8",
        )

        skills = discover(sd)
        assert "backslash" not in skills

    def test_source_wrong_suffix_rejected(self, tmp_path):
        """query type with .py suffix is rejected (suffix enforcement)."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        q = sd / "wrong-suffix"
        q.mkdir()
        (q / "skill_def.md").write_text(
            "---\n"
            "name: wrong-suffix\n"
            "type: query\n"
            "source: wrong.py\n"
            "risk: low\n"
            "description: Wrong suffix\n"
            "---\n\nBad.\n",
            encoding="utf-8",
        )

        skills = discover(sd)
        assert "wrong-suffix" not in skills

    def test_source_mutation_wrong_suffix_rejected(self, tmp_path):
        """mutation type with .sql suffix is rejected."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        m = sd / "mut-wrong-suffix"
        m.mkdir()
        (m / "skill_def.md").write_text(
            "---\n"
            "name: mut-wrong-suffix\n"
            "type: mutation\n"
            "source: query.sql\n"
            "risk: low\n"
            "description: Mutation with SQL suffix\n"
            "---\n\nBad.\n",
            encoding="utf-8",
        )

        skills = discover(sd)
        assert "mut-wrong-suffix" not in skills

    def test_source_hidden_file_rejected(self, tmp_path):
        """source: .secret.sql is rejected (hidden file prevention)."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        q = sd / "hidden-source"
        q.mkdir()
        (q / "skill_def.md").write_text(
            "---\n"
            "name: hidden-source\n"
            "type: query\n"
            "source: .secret.sql\n"
            "risk: low\n"
            "description: Hidden file source\n"
            "---\n\nBad.\n",
            encoding="utf-8",
        )

        skills = discover(sd)
        assert "hidden-source" not in skills

    def test_source_custom_name(self, tmp_path):
        """Custom source filename (e.g. daily-revenue.sql) works correctly."""
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()
        q = sd / "custom-name"
        q.mkdir()
        (q / "skill_def.md").write_text(
            "---\n"
            "name: custom-name\n"
            "type: query\n"
            "source: daily-revenue.sql\n"
            "risk: low\n"
            "description: Custom source filename\n"
            "---\n\nCustom.\n",
            encoding="utf-8",
        )
        (q / "daily-revenue.sql").write_text("SELECT 1", encoding="utf-8")

        skills = discover(sd)
        assert "custom-name" in skills

    def test_source_stored_in_metadata(self, discovered_skills):
        """source field is accessible on SkillMetadata after discover()."""
        meta_q = discovered_skills["test-query"]
        assert meta_q.source == "query.sql"

        meta_m = discovered_skills["test-mutation"]
        assert meta_m.source == "mutation.py"

    def test_source_symlink_escape_rejected(self, tmp_path):
        """Symlink in skill dir pointing outside is rejected (resolved path check)."""
        import os
        from skill_loader import discover

        sd = tmp_path / "skills"
        sd.mkdir()

        # Create external SQL file outside skills directory
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        (external_dir / "secret.sql").write_text("SELECT secret FROM passwords", encoding="utf-8")

        # Create skill with symlink pointing to external file
        q = sd / "symlink-escape"
        q.mkdir()
        (q / "skill_def.md").write_text(
            "---\n"
            "name: symlink-escape\n"
            "type: query\n"
            "source: query.sql\n"
            "risk: low\n"
            "description: Symlink escape attempt\n"
            "---\n\nBad.\n",
            encoding="utf-8",
        )
        os.symlink(external_dir / "secret.sql", q / "query.sql")

        skills = discover(sd)
        assert "symlink-escape" not in skills
