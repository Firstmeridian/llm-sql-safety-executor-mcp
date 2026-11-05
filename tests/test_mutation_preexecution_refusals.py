"""Confirmation refusals describe only outcomes the framework can establish."""

import shutil
from dataclasses import replace

from fastmcp import Client
from fastmcp.exceptions import ToolError
import pytest

from tests.test_mutation_skill_reload import (
    execute,
    observed,
    prepare,
    reload_deployment as reload_deployment,
)
from tests.test_v38_config import bundle as bundle


NO_WRITE = "this request wrote nothing"


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("change,reason", [
    ("delete", "Skill 'change-n' not found"),
    ("disable", "Skill 'change-n' not found"),
    ("rename", "Unexpected parameter(s): ['new_n']"),
    ("scope", "cannot run on connection 'demo'; allowed connection_ids"),
])
async def test_old_confirmation_setup_refusal(
    reload_deployment, monkeypatch, mode, change, reason,
):
    from sql_safety_executor.core import mutations

    server, runtime, root, path = reload_deployment()
    async with Client(server, mode=mode) as client:
        old = await prepare(client)
        definition = root / "change-n/skill_def.md"
        if change == "delete":
            shutil.rmtree(definition.parent)
        else:
            text = definition.read_text()
            if change == "disable":
                text = text.replace("risk: medium", "risk: medium\nenabled: false")
            elif change == "rename":
                text = text.replace("  new_n:", "  replacement_n:")
                source = definition.parent / "mutation.py"
                source.write_text(source.read_text().replace("new_n", "replacement_n"))
            else:
                text = text.replace("databases: [sqlite]", "databases: [sqlite]\nconnection_ids: [other]")
            definition.write_text(text)
        receipt = (await client.call_tool("reload_skills", {
            "skill_type": "mutation",
        })).structured_content
        assert receipt["success"] and receipt["invalidated_previews"] == 1
        assert len(runtime.tokens) == 0

        def unexpected_consumption(*args, **kwargs):
            pytest.fail("setup refusal must precede token checks")

        monkeypatch.setattr(mutations, "_consume_mutation_preview_token", unexpected_consumption)
        with pytest.raises(ToolError) as error:
            await execute(client, old)
        assert reason in str(error.value)
        assert NO_WRITE in str(error.value)
        assert "let the user decide whether to preview again" in str(error.value)
        # The same setup error in preview retains its original message.
        with pytest.raises(ToolError) as preview_error:
            await prepare(client)
        assert reason in str(preview_error.value)
        assert NO_WRITE not in str(preview_error.value)
        assert observed(path) == 7 and len(runtime.tokens) == 0
        noop = runtime.reload_skills("mutation")
        assert noop["invalidated_previews"] == 0


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_missing_token_refuses_without_consuming_pending_preview(reload_deployment, mode):
    server, runtime, _, path = reload_deployment()
    async with Client(server, mode=mode) as client:
        old = await prepare(client)
        with pytest.raises(ToolError) as error:
            await client.call_tool("execute_mutation_skill", {
                "skill_name": "change-n", "params": {"order_id": 1, "new_n": 8},
                "connection_id": "demo", "confirm": True,
            })
        assert "preview_token is required" in str(error.value)
        assert "confirm=false first" in str(error.value)
        assert NO_WRITE in str(error.value)
        assert observed(path) == 7 and len(runtime.tokens) == 1
        result = await execute(client, old)
        assert result["success"] and result["execution_outcome"] == "committed"
        assert observed(path) == 8 and len(runtime.tokens) == 0


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("phase", ["construction", "execution"])
async def test_trusted_python_failure_does_not_claim_no_write(
    reload_deployment, monkeypatch, mode, phase,
):
    server, runtime, _, path = reload_deployment("imperative")
    async with Client(server, mode=mode) as client:
        old = await prepare(client)
        mutation_class = runtime.catalog.get_skills_cache()["change-n"]._mutation_class

        def write_then_fail(self, *args, **kwargs):
            self.adapter.execute_write("UPDATE orders SET n=99 WHERE id=1", {}, expected_rowcount=1)
            raise ValueError("trusted Python failed after writing")

        if phase == "construction":
            original_init = mutation_class.__init__

            def failing_init(self, *args, **kwargs):
                original_init(self, *args, **kwargs)
                write_then_fail(self)

            monkeypatch.setattr(mutation_class, "__init__", failing_init)
            with pytest.raises(ToolError) as error:
                await execute(client, old)
            assert "trusted Python failed after writing" in str(error.value)
            assert NO_WRITE not in str(error.value)
            assert len(runtime.tokens) == 0
        else:
            monkeypatch.setattr(mutation_class, "execute_with_binding", write_then_fail)
            result = await execute(client, old)
            assert not result["success"] and result["execution_outcome"] == "unknown"
            assert NO_WRITE not in result["error"]
            assert len(runtime.tokens) == 0
        assert observed(path) == 99


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("rejection", ["missing", "invalid", "mismatch", "expired", "replay"])
async def test_token_refusal_precedes_successful_writing_constructor(
    reload_deployment, monkeypatch, mode, rejection,
):
    """DB truth, not a callback mock, detects unauthorized construction."""
    from sql_safety_executor.core.proposals import _preview_token_digest

    server, runtime, _, path = reload_deployment("imperative")
    async with Client(server, mode=mode) as client:
        old = await prepare(client)
        token = old["preview_token"]
        expected = 7
        if rejection == "replay":
            assert (await execute(client, old))["success"]
            expected = 8
        elif rejection == "expired":
            digest = _preview_token_digest(token)
            runtime.tokens._entries[digest] = replace(runtime.tokens._entries[digest], expires_at=0)
        mutation_class = runtime.catalog.get_skills_cache()["change-n"]._mutation_class
        original_init = mutation_class.__init__
        constructions = []

        def writing_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            constructions.append(True)
            self.adapter.execute_write("UPDATE orders SET n=99 WHERE id=1", {}, expected_rowcount=1)

        monkeypatch.setattr(mutation_class, "__init__", writing_init)
        args = {
            "skill_name": "change-n", "params": {"order_id": 1, "new_n": 8},
            "connection_id": "demo", "confirm": True,
        }
        if rejection != "missing":
            args["preview_token"] = "invalid-token" if rejection == "invalid" else token
        if rejection == "mismatch":
            args["params"]["new_n"] = 9
        with pytest.raises(ToolError) as error:
            await client.call_tool("execute_mutation_skill", args)
        assert NO_WRITE in str(error.value)
        assert not constructions
        assert observed(path) == expected
        assert len(runtime.tokens) == (1 if rejection in {"missing", "invalid", "mismatch"} else 0)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.parametrize("phase", ["construction", "validation"])
async def test_revalidation_refusal_cannot_erase_trusted_python_effects(
    reload_deployment, monkeypatch, mode, phase,
):
    server, runtime, _, path = reload_deployment("imperative")
    async with Client(server, mode=mode) as client:
        old = await prepare(client)
        mutation_class = runtime.catalog.get_skills_cache()["change-n"]._mutation_class

        def write(self):
            self.adapter.execute_write("UPDATE orders SET n=99 WHERE id=1", {}, expected_rowcount=1)

        if phase == "construction":
            original_init = mutation_class.__init__

            def writing_init(self, *args, **kwargs):
                assert len(runtime.tokens) == 0
                original_init(self, *args, **kwargs)
                write(self)

            monkeypatch.setattr(mutation_class, "__init__", writing_init)

        def reject(self, params):
            if phase == "validation":
                write(self)
            return {"valid": False, "errors": ["Fixture business precondition failed"]}

        monkeypatch.setattr(mutation_class, "validate", reject)
        monkeypatch.setattr(mutation_class, "execute_with_binding",
                            lambda *_a, **_k: pytest.fail("Rejected validation must not execute"))
        result = await execute(client, old)
        assert result["error_code"] == "validation_failed"
        assert result["execution_outcome"] == "unknown"
        assert NO_WRITE not in result["error"]
        assert observed(path) == 99 and len(runtime.tokens) == 0
        with pytest.raises(ToolError) as replay:
            await execute(client, old)
        assert NO_WRITE in str(replay.value)
        assert observed(path) == 99


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_generation_rejection_after_preview_python_does_not_claim_no_write(
    reload_deployment, monkeypatch, mode,
):
    server, runtime, root, path = reload_deployment("imperative")
    mutation_class = runtime.catalog.get_skills_cache()["change-n"]._mutation_class
    original_preview = mutation_class.preview

    def writing_preview(self, params):
        result = original_preview(self, params)
        self.adapter.execute_write("UPDATE orders SET n=99 WHERE id=1", {}, expected_rowcount=1)
        definition = root / "change-n/skill_def.md"
        definition.write_text(definition.read_text().replace("Change an isolated", "Change a revised isolated"))
        assert runtime.reload_skills("mutation")["changed"] == ["change-n"]
        return result

    monkeypatch.setattr(mutation_class, "preview", writing_preview)
    async with Client(server, mode=mode) as client:
        with pytest.raises(ToolError, match="definition changed") as error:
            await prepare(client)
    assert NO_WRITE not in str(error.value)
    assert observed(path) == 99 and len(runtime.tokens) == 0
