"""
Tests for Mutation Skills — validate/preview/execute workflow

Covers:
- Dry-run (confirm=false) returns preview, no database changes (#8)
- Confirm execution writes data (#9)
- Idempotent write strategy (#10)
- Mutation error sanitization (#27)
- MutationBase.run_execute() error handling

Uses SQLite in-memory database for fast, isolated testing.

Usage:
    pytest tests/test_mutation_skills.py -v
"""

import importlib.util
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock

# Add project root and _lib to path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "_lib"))


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def adapter_with_orders():
    """
    Create a SQLiteAdapter with orders table.

    Orders have status field for state machine testing.
    """
    from db_adapter import SQLiteAdapter
    from sqlalchemy import text

    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    assert adapter._engine is not None

    with adapter._engine.connect() as conn:
        with conn.begin():
            conn.execute(text("""
                CREATE TABLE orders (
                    id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'pending',
                    amount REAL NOT NULL
                )
            """))
            conn.execute(text("""
                INSERT INTO orders (id, status, amount) VALUES
                (1, 'pending', 100.00),
                (2, 'confirmed', 250.00),
                (3, 'shipped', 75.50)
            """))

    yield adapter
    adapter.close()


@pytest.fixture
def adapter_with_duplicate_orders():
    """Create a deliberately invalid schema with duplicate order IDs."""
    from db_adapter import SQLiteAdapter
    from sqlalchemy import text

    adapter = SQLiteAdapter(":memory:")
    adapter.connect()
    assert adapter._engine is not None

    with adapter._engine.connect() as conn:
        with conn.begin():
            conn.execute(text("""
                CREATE TABLE orders (
                    id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    amount REAL NOT NULL
                )
            """))
            conn.execute(text("""
                INSERT INTO orders (id, status, amount) VALUES
                (7, 'confirmed', 100.00),
                (7, 'confirmed', 250.00)
            """))

    yield adapter
    adapter.close()


@pytest.fixture
def mock_audit_logger(tmp_path):
    """Create an AuditLogger pointing to a temp file."""
    from audit import AuditLogger
    return AuditLogger(log_path=tmp_path / "test_audit.jsonl")


class SimpleMutation:
    """A simple mutation for testing that updates order status."""

    def __init__(self, adapter, audit_logger):
        self.adapter = adapter
        self.logger = audit_logger

    def validate(self, params):
        result = self.adapter.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": params["order_id"]},
        )
        if not result:
            return {"valid": False, "errors": [f"Order {params['order_id']} not found"]}
        return {"valid": True, "current_status": result[0].status}

    def preview(self, params):
        result = self.adapter.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": params["order_id"]},
        )
        current = result[0].status if result else "unknown"
        return {
            "preview_sql": "UPDATE orders SET status = :new_status WHERE id = :order_id",
            "bound_params": params,
            "affected_rows_estimate": 1,
            "current_status": current,
        }

    def execute(self, params):
        return self.adapter.execute_write(
            "UPDATE orders SET status = :new_status WHERE id = :order_id AND status = :expected",
            params={
                "new_status": params["new_status"],
                "order_id": params["order_id"],
                "expected": params.get("expected", "pending"),
            },
        )


def _load_demo_reset_mutation(adapter, audit_logger):
    mutation_path = (
        Path(__file__).parent.parent
        / "skills"
        / "sample-reset-order-to-pending"
        / "mutation.py"
    )
    spec = importlib.util.spec_from_file_location(
        "test_reset_demo_order_to_pending_mutation",
        mutation_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Mutation(adapter, audit_logger)


class TestResetDemoOrderToPending:
    """Coverage for the portable demo/test compensating mutation."""

    def test_preview_binds_explicit_expected_state_without_write(
        self, adapter_with_orders, mock_audit_logger
    ):
        mutation = _load_demo_reset_mutation(
            adapter_with_orders, mock_audit_logger
        )
        params = {"order_id": 2, "expected_status": "confirmed"}

        validation = mutation.validate(params)
        preview = mutation.preview(params)
        binding = mutation.build_execution_binding(params, validation, preview)

        assert validation["valid"] is True
        assert preview["current_status"] == "confirmed"
        assert preview["new_status"] == "pending"
        assert "preview_sql" not in preview
        assert "bound_params" not in preview
        assert binding == {"expected_status": "confirmed"}
        current = adapter_with_orders.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": 2},
        )
        assert current[0].status == "confirmed"

    def test_managed_execute_resets_expected_order_to_pending(
        self, adapter_with_orders, mock_audit_logger
    ):
        from mutation_base import run_managed_mutation

        mutation = _load_demo_reset_mutation(
            adapter_with_orders, mock_audit_logger
        )
        params = {"order_id": 2, "expected_status": "confirmed"}

        result = run_managed_mutation(
            plan=mutation.managed_plan,
            adapter=adapter_with_orders,
            audit_logger=mock_audit_logger,
            params=params,
            execution_binding={"expected_status": "confirmed"},
            skill_name="sample-reset-order-to-pending",
        )

        assert result["success"] is True
        assert result["rowcount"] == 1
        assert result["previous_status"] == "confirmed"
        assert result["new_status"] == "pending"
        current = adapter_with_orders.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": 2},
        )
        assert current[0].status == "pending"

    def test_expected_status_mismatch_and_stale_binding_fail_closed(
        self, adapter_with_orders, mock_audit_logger
    ):
        from mutation_base import MutationExecutionError, run_managed_mutation

        mutation = _load_demo_reset_mutation(
            adapter_with_orders, mock_audit_logger
        )
        assert mutation.validate(
            {"order_id": 1, "expected_status": "confirmed"}
        )["valid"] is False

        adapter_with_orders.execute_write(
            "UPDATE orders SET status = 'shipped' WHERE id = :order_id",
            {"order_id": 2},
        )
        with pytest.raises(
            MutationExecutionError,
            match="no longer matches the previewed state",
        ) as raised:
            run_managed_mutation(
                plan=mutation.managed_plan,
                adapter=adapter_with_orders,
                audit_logger=mock_audit_logger,
                params={"order_id": 2, "expected_status": "confirmed"},
                execution_binding={"expected_status": "confirmed"},
                skill_name="sample-reset-order-to-pending",
            )
        assert raised.value.execution_outcome == "rolled_back"

    def test_direct_unbound_execute_is_rejected(
        self, adapter_with_orders, mock_audit_logger
    ):
        from fastmcp.exceptions import ToolError

        mutation = _load_demo_reset_mutation(
            adapter_with_orders, mock_audit_logger
        )
        with pytest.raises(ToolError, match="framework confirmation path"):
            mutation.execute(
                {"order_id": 2, "expected_status": "confirmed"}
            )

    def test_duplicate_order_id_is_rejected_during_validation(
        self, adapter_with_duplicate_orders, mock_audit_logger
    ):
        """Portable read-side defense diagnoses a violated schema contract."""
        mutation = _load_demo_reset_mutation(
            adapter_with_duplicate_orders,
            mock_audit_logger,
        )

        validation = mutation.validate(
            {"order_id": 7, "expected_status": "confirmed"}
        )
        preview = mutation.preview(
            {"order_id": 7, "expected_status": "confirmed"}
        )

        assert validation["valid"] is False
        assert "not uniquely identified" in validation["errors"][0]
        assert "not uniquely identified" in preview["error"]

        rows = adapter_with_duplicate_orders.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": 7},
        )
        assert [row.status for row in rows] == ["confirmed", "confirmed"]


# =============================================================================
# test_dry_run_no_write (#8)
# =============================================================================

class TestDryRun:
    """Tests for preview mode — no writes to database."""

    def test_dry_run_no_write(self, adapter_with_orders, mock_audit_logger):
        """#8: confirm=False returns preview, database unchanged."""
        mutation = SimpleMutation(adapter_with_orders, mock_audit_logger)

        # Validate
        validation = mutation.validate({"order_id": 1, "new_status": "shipped"})
        assert validation["valid"] is True
        assert validation["current_status"] == "pending"

        # Preview
        preview = mutation.preview({"order_id": 1, "new_status": "shipped"})
        assert "preview_sql" in preview
        assert preview["current_status"] == "pending"

        # Verify NO writes happened
        result = adapter_with_orders.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": 1},
        )
        assert result[0].status == "pending"

    def test_validate_nonexistent_order(self, adapter_with_orders, mock_audit_logger):
        """Validation fails for non-existent order."""
        mutation = SimpleMutation(adapter_with_orders, mock_audit_logger)

        validation = mutation.validate({"order_id": 999, "new_status": "shipped"})
        assert validation["valid"] is False
        assert any("not found" in e for e in validation["errors"])


# =============================================================================
# test_confirm_writes_data (#9)
# =============================================================================

class TestConfirmExecution:
    """Tests for execute mode — actual database changes."""

    def test_confirm_writes_data(self, adapter_with_orders, mock_audit_logger):
        """#9: confirm=True writes data and verifies."""
        mutation = SimpleMutation(adapter_with_orders, mock_audit_logger)

        params = {
            "order_id": 1,
            "new_status": "confirmed",
            "expected": "pending",
        }

        result = mutation.execute(params)
        assert result["success"] is True
        assert result["rowcount"] == 1

        # Verify the write
        verify = adapter_with_orders.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": 1},
        )
        assert verify[0].status == "confirmed"

    def test_optimistic_lock_prevents_conflict(
        self, adapter_with_orders, mock_audit_logger
    ):
        """Optimistic locking: concurrent status change results in rowcount=0."""
        mutation = SimpleMutation(adapter_with_orders, mock_audit_logger)

        # First update succeeds
        result1 = mutation.execute({
            "order_id": 1,
            "new_status": "confirmed",
            "expected": "pending",
        })
        assert result1["rowcount"] == 1

        # Second update with stale expected status returns rowcount=0
        result2 = mutation.execute({
            "order_id": 1,
            "new_status": "shipped",
            "expected": "pending",  # Wrong — it's now 'confirmed'
        })
        assert result2["rowcount"] == 0


# =============================================================================
# test_idempotent_write (#10)
# =============================================================================

class TestIdempotentWrite:
    """Tests for idempotent write patterns."""

    def test_idempotent_write(self, adapter_with_orders, mock_audit_logger):
        """#10: Same update applied twice with optimistic lock is safe."""
        mutation = SimpleMutation(adapter_with_orders, mock_audit_logger)

        params = {
            "order_id": 1,
            "new_status": "confirmed",
            "expected": "pending",
        }

        # First call succeeds
        result1 = mutation.execute(params)
        assert result1["rowcount"] == 1

        # Second call with same expected status: rowcount=0 (idempotent-safe)
        result2 = mutation.execute(params)
        assert result2["rowcount"] == 0

        # Order is still in the correct state
        verify = adapter_with_orders.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": 1},
        )
        assert verify[0].status == "confirmed"


# =============================================================================
# test_mutation_error_sanitization (#27)
# =============================================================================

class TestErrorSanitization:
    """Tests for error sanitization through MutationBase.run_execute()."""

    def test_mutation_error_sanitization(self, adapter_with_orders, mock_audit_logger):
        """#27: Errors are sanitized via _handle_error() + ToolError."""
        from mutation_base import MutationBase
        from fastmcp.exceptions import ToolError

        class FailingMutation(MutationBase):
            def validate(self, params):
                return {"valid": True}

            def preview(self, params):
                return {"preview_sql": "N/A"}

            def execute(self, params):
                # Trigger an error via invalid SQL
                return self.adapter.execute_write(
                    "UPDATE nonexistent_xyz_table SET x = :v",
                    params={"v": 1},
                )

        mutation = FailingMutation(adapter_with_orders, mock_audit_logger)

        with pytest.raises(ToolError) as exc_info:
            mutation.run_execute(
                {"v": 1},
                skill_name="test-fail",
                mode="execute",
            )

        # Error should be sanitized (not contain raw stack trace)
        error_msg = str(exc_info.value)
        assert "Error:" in error_msg
        # Should NOT contain internal details like file paths
        assert "sqlalchemy" not in error_msg.lower()


# =============================================================================
# MutationBase.run_execute() audit logging
# =============================================================================

class TestRunExecuteAudit:
    """Tests for run_execute() audit logging behavior."""

    def test_run_execute_logs_success(self, adapter_with_orders, tmp_path):
        """run_execute() logs successful operations to audit file."""
        import json
        from audit import AuditLogger
        from mutation_base import MutationBase

        log_path = tmp_path / "audit.jsonl"
        audit = AuditLogger(log_path=log_path)

        class SuccessMutation(MutationBase):
            def validate(self, params):
                return {"valid": True}

            def preview(self, params):
                return {}

            def execute(self, params):
                return self.adapter.execute_write(
                    "UPDATE orders SET status = :new_status WHERE id = :order_id",
                    params={"new_status": params["new_status"], "order_id": params["order_id"]},
                )

        mutation = SuccessMutation(adapter_with_orders, audit)
        result = mutation.run_execute(
            {"order_id": 1, "new_status": "confirmed"},
            skill_name="test-success",
            mode="execute",
        )

        assert result["success"] is True
        assert result["_audit_logged"] is True
        assert result.execution_outcome == "unknown"

        # Check audit log
        log_content = log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(log_content)
        assert entry["skill_name"] == "test-success"
        assert entry["mode"] == "execute"
        assert entry["success"] is True
        assert entry["execution_outcome"] == "unknown"

    def test_run_execute_reports_audit_write_failure(self, adapter_with_orders):
        """run_execute() exposes best-effort audit write failure in the result."""
        from mutation_base import MutationBase

        class FailingAuditLogger:
            def log(self, **kwargs):
                return False

        class SuccessMutation(MutationBase):
            def validate(self, params):
                return {"valid": True}

            def preview(self, params):
                return {}

            def execute(self, params):
                return {"success": True, "rowcount": 1}

        mutation = SuccessMutation(adapter_with_orders, FailingAuditLogger())
        result = mutation.run_execute(
            {"order_id": 1},
            skill_name="test-audit-failure",
            mode="execute",
        )

        assert result["success"] is True
        assert result["_audit_logged"] is False
        assert result.execution_outcome == "unknown"

    def test_obsolete_exact_attribute_cannot_promote_plain_imperative_success(
        self,
        adapter_with_orders,
        mock_audit_logger,
    ):
        """A direct base caller cannot revive the removed exact flag."""
        from mutation_base import MutationBase

        class ObsoleteFlagMutation(MutationBase):
            exact_transaction_outcome = True

            def validate(self, params):
                return {"valid": True}

            def preview(self, params):
                return {}

            def execute(self, params):
                return {"success": True, "rowcount": 1}

        mutation = ObsoleteFlagMutation(adapter_with_orders, mock_audit_logger)
        result = mutation.run_execute(
            {"order_id": 1},
            skill_name="sample-update-order-status",
        )

        assert result.execution_outcome == "unknown"

    @pytest.mark.parametrize(
        "skill_name",
        ["sample-update-order-status", "sample-reset-order-to-pending"],
    )
    def test_managed_success_requires_adapter_commit_evidence(
        self,
        skill_name,
        adapter_with_orders,
        mock_audit_logger,
    ):
        """A managed plan cannot claim COMMIT from a plain adapter dict."""
        import json
        from mutation_base import (
            MutationExecutionError,
            run_managed_mutation,
        )
        from skill_loader import discover

        bundled_dir = Path(__file__).resolve().parent.parent / "skills"
        meta = discover(bundled_dir)[skill_name]
        plan = meta._managed_mutation_plan
        assert plan is not None

        class PlainResultAdapter:
            def execute_write(self, sql, params, *, expected_rowcount):
                return {"success": True, "rowcount": expected_rowcount}

            def _handle_error(self, error):
                return "Database operation failed."

        if skill_name == "sample-update-order-status":
            params = {"order_id": 1, "new_status": "confirmed"}
        else:
            params = {"order_id": 2, "expected_status": "confirmed"}

        with pytest.raises(MutationExecutionError) as raised:
            run_managed_mutation(
                plan=plan,
                adapter=PlainResultAdapter(),
                audit_logger=mock_audit_logger,
                params=params,
                execution_binding={"expected_status": "pending"},
                skill_name=skill_name,
            )

        assert raised.value.error_code == "missing_commit_evidence"
        assert raised.value.execution_outcome == "unknown"
        assert raised.value.audit_logged is True
        entry = json.loads(mock_audit_logger.log_path.read_text(encoding="utf-8"))
        assert entry["success"] is False
        assert entry["execution_outcome"] == "unknown"
        assert entry["error_code"] == "missing_commit_evidence"

    def test_custom_skill_cannot_self_promote_adapter_commit_evidence(
        self,
        adapter_with_orders,
        mock_audit_logger,
    ):
        """The removed flag cannot promote an imperative adapter result."""
        from mutation_base import MutationBase

        class SelfDeclaredExactMutation(MutationBase):
            exact_transaction_outcome = True

            def validate(self, params):
                return {"valid": True}

            def preview(self, params):
                return {}

            def execute(self, params):
                return self.adapter.execute_write(
                    "UPDATE orders SET status = :status WHERE id = :order_id",
                    {"status": "confirmed", "order_id": params["order_id"]},
                    expected_rowcount=1,
                )

        mutation = SelfDeclaredExactMutation(
            adapter_with_orders,
            mock_audit_logger,
        )
        result = mutation.run_execute(
            {"order_id": 1},
            skill_name="custom-exact",
        )

        assert result["success"] is True
        assert result.execution_outcome == "unknown"

    def test_custom_rowcount_mismatch_does_not_claim_whole_skill_rollback(
        self,
        adapter_with_orders,
        mock_audit_logger,
    ):
        """One rolled-back statement cannot prove earlier custom work vanished."""
        from db_adapter import WriteExecutionPhase
        from mutation_base import (
            MutationBase,
            MutationExecutionError,
            WriteExecutionError,
            WriteExecutionOutcome,
        )

        class SyntheticRowcountMismatch(WriteExecutionError):
            actual_rowcount = 0

        class MultiStatementMutation(MutationBase):
            def validate(self, params):
                return {"valid": True}

            def preview(self, params):
                return {}

            def execute(self, params):
                error = SyntheticRowcountMismatch(
                    "Second statement affected zero rows.",
                    execution_outcome=WriteExecutionOutcome.ROLLED_BACK,
                    phase=WriteExecutionPhase.ROWCOUNT_CHECK,
                    error_code="expected_rowcount_mismatch",
                )
                raise error

        mutation = MultiStatementMutation(adapter_with_orders, mock_audit_logger)
        with pytest.raises(MutationExecutionError) as raised:
            mutation.run_execute({"order_id": 1}, skill_name="custom-multi-write")

        assert raised.value.execution_outcome == "unknown"
        assert raised.value.error_code == "execution_outcome_unknown"
        assert "whole Skill outcome cannot be confirmed" in str(raised.value)
        assert "the write was not committed" not in str(raised.value)

    @pytest.mark.parametrize(
        "invalid_result",
        [
            None,
            {},
            {"success": "true"},
            {"success": False, "error": "caught write failure"},
        ],
    )
    def test_custom_skill_invalid_success_result_is_structured_unknown(
        self,
        adapter_with_orders,
        mock_audit_logger,
        invalid_result,
    ):
        """Malformed or self-reported failures cannot be upgraded to success."""
        from mutation_base import MutationBase, MutationExecutionError

        class InvalidResultMutation(MutationBase):
            def validate(self, params):
                return {"valid": True}

            def preview(self, params):
                return {}

            def execute(self, params):
                return invalid_result

        mutation = InvalidResultMutation(adapter_with_orders, mock_audit_logger)
        with pytest.raises(MutationExecutionError) as raised:
            mutation.run_execute(
                {"order_id": 1},
                skill_name="test-invalid-success-result",
            )

        assert raised.value.execution_outcome == "unknown"
        assert raised.value.error_code == "invalid_skill_result"

    def test_run_execute_rejects_unhandled_execution_binding(
        self,
        adapter_with_orders,
        mock_audit_logger,
    ):
        """A skill must explicitly honor any non-empty preview-state binding."""
        from mutation_base import MutationBase
        from fastmcp.exceptions import ToolError

        class UnboundMutation(MutationBase):
            def validate(self, params):
                return {"valid": True}

            def preview(self, params):
                return {}

            def execute(self, params):
                return {"success": True, "rowcount": 1}

        mutation = UnboundMutation(adapter_with_orders, mock_audit_logger)
        with pytest.raises(ToolError, match="does not implement execute_with_binding"):
            mutation.run_execute(
                {"order_id": 1},
                skill_name="test-unhandled-binding",
                execution_binding={"expected_status": "pending"},
            )

    def test_run_execute_logs_toolerror_from_execute(self, adapter_with_orders, tmp_path):
        """run_execute() audit-logs ToolError raised by execute() before re-raising."""
        import json
        from audit import AuditLogger
        from mutation_base import MutationBase
        from fastmcp.exceptions import ToolError

        log_path = tmp_path / "audit.jsonl"
        audit = AuditLogger(log_path=log_path)

        class BusinessErrorMutation(MutationBase):
            def validate(self, params):
                return {"valid": True}

            def preview(self, params):
                return {}

            def execute(self, params):
                raise ToolError("Order 999 not found")

        mutation = BusinessErrorMutation(adapter_with_orders, audit)
        with pytest.raises(ToolError, match="Order 999 not found"):
            mutation.run_execute(
                {"order_id": 999},
                skill_name="test-biz-error",
                mode="execute",
            )

        # Verify audit log records the failure
        log_content = log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(log_content)
        assert entry["skill_name"] == "test-biz-error"
        assert entry["mode"] == "execute"
        assert entry["success"] is False
        assert "not found" in entry["error"]


class TestManagedMutationExecution:
    """Framework-only execution guarantees for declarative mutations."""

    @pytest.mark.parametrize("field", ["error", "error_code"])
    def test_plan_cannot_inject_audit_error_fields(self, field):
        from mutation_base import (
            ManagedMutationPlan,
            ManagedMutationValue,
            validate_managed_mutation_plan,
        )

        with pytest.raises(TypeError, match="reserved"):
            validate_managed_mutation_plan(
                ManagedMutationPlan(
                    "DELETE FROM orders WHERE id = :order_id",
                    (ManagedMutationValue.from_params("order_id"),),
                    1,
                    (ManagedMutationValue.constant(field, "fake error"),),
                )
            )

    def test_plan_validation_rejects_ambiguous_or_mutable_contracts(self):
        from mutation_base import (
            ManagedMutationPlan,
            ManagedMutationValue,
            validate_managed_mutation_plan,
        )

        sql = "DELETE FROM orders WHERE id = :order_id"
        parameter = ManagedMutationValue.from_params("order_id")

        with pytest.raises(TypeError, match="non-negative integer"):
            validate_managed_mutation_plan(
                ManagedMutationPlan(sql, (parameter,), True)
            )
        with pytest.raises(TypeError, match="must be tuples"):
            validate_managed_mutation_plan(
                ManagedMutationPlan(sql, [parameter], 1)  # type: ignore[arg-type]
            )
        with pytest.raises(TypeError, match="finite"):
            validate_managed_mutation_plan(
                ManagedMutationPlan(
                    sql,
                    (ManagedMutationValue.constant("order_id", float("inf")),),
                    1,
                )
            )
        with pytest.raises(TypeError, match="safe identifiers"):
            validate_managed_mutation_plan(
                ManagedMutationPlan(
                    sql,
                    (ManagedMutationValue.from_params("order_id", ""),),
                    1,
                )
            )
        with pytest.raises(TypeError, match="reserved"):
            validate_managed_mutation_plan(
                ManagedMutationPlan(
                    sql,
                    (parameter,),
                    1,
                    (ManagedMutationValue.from_params("success", "order_id"),),
                )
            )

    def test_missing_binding_fails_before_adapter_write(self, mock_audit_logger):
        from mutation_base import (
            ManagedMutationPlan,
            ManagedMutationValue,
            MutationExecutionError,
            run_managed_mutation,
        )

        class RecordingAdapter:
            calls = 0

            def execute_write(self, *_args, **_kwargs):
                self.calls += 1
                raise AssertionError("write must not be called")

            def _handle_error(self, _error):
                return "Database operation failed."

        adapter = RecordingAdapter()
        plan = ManagedMutationPlan(
            sql="UPDATE orders SET status = :status WHERE id = :order_id",
            parameters=(
                ManagedMutationValue.from_params("order_id"),
                ManagedMutationValue.from_binding("status", "preview_status"),
            ),
            expected_rowcount=1,
        )

        with pytest.raises(MutationExecutionError) as raised:
            run_managed_mutation(
                plan=plan,
                adapter=adapter,
                audit_logger=mock_audit_logger,
                params={"order_id": 1},
                execution_binding={},
                skill_name="managed-write",
            )

        assert adapter.calls == 0
        assert raised.value.execution_outcome == "not_executed"
        assert raised.value.error_code == "managed_plan_resolution_failed"

    def test_non_scalar_binding_fails_before_adapter_write(self, mock_audit_logger):
        from mutation_base import (
            ManagedMutationPlan,
            ManagedMutationValue,
            MutationExecutionError,
            run_managed_mutation,
        )

        class RecordingAdapter:
            calls = 0

            def execute_write(self, *_args, **_kwargs):
                self.calls += 1
                raise AssertionError("write must not be called")

            def _handle_error(self, _error):
                return "Database operation failed."

        adapter = RecordingAdapter()
        plan = ManagedMutationPlan(
            sql="DELETE FROM orders WHERE id = :order_id",
            parameters=(ManagedMutationValue.from_binding("order_id"),),
            expected_rowcount=1,
        )

        with pytest.raises(MutationExecutionError) as raised:
            run_managed_mutation(
                plan=plan,
                adapter=adapter,
                audit_logger=mock_audit_logger,
                params={},
                execution_binding={"order_id": [1]},
                skill_name="managed-write",
            )

        assert adapter.calls == 0
        assert raised.value.execution_outcome == "not_executed"
