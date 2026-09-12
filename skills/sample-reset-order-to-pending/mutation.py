"""Portable demo mutation that resets an expected order state to pending."""

from fastmcp.exceptions import ToolError
from mutation_base import MutationBase, MutationWriteError  # type: ignore[import-not-found]
from db_adapter import ExpectedRowcountMismatchError, WriteExecutionError


RESETTABLE_STATUSES = frozenset(
    {"confirmed", "shipped", "delivered", "cancelled", "returned"}
)


class Mutation(MutationBase):
    """Reset a demo order to pending with preview-state optimistic locking."""

    exact_transaction_outcome = True

    def _read_status(self, order_id: int) -> tuple[str | None, str | None]:
        result = self.adapter.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": order_id},
        )
        if isinstance(result, str) and result.startswith("Error:"):
            return None, "Database query failed"
        if not result:
            return None, f"Order {order_id} not found"
        if len(result) != 1:
            return None, (
                f"Order {order_id} is not uniquely identified; "
                "orders.id must be PRIMARY KEY or UNIQUE"
            )
        return result[0].status, None  # type: ignore[union-attr]

    @staticmethod
    def _validate_expected_status(expected_status: object) -> str | None:
        if not isinstance(expected_status, str):
            return "expected_status must be a string"
        if expected_status not in RESETTABLE_STATUSES:
            return (
                f"Status '{expected_status}' cannot be reset by this demo Skill; "
                f"expected one of {sorted(RESETTABLE_STATUSES)}"
            )
        return None

    def validate(self, params: dict) -> dict:
        order_id = params["order_id"]
        expected_status = params["expected_status"]
        expected_error = self._validate_expected_status(expected_status)
        if expected_error:
            return {"valid": False, "errors": [expected_error]}

        current_status, error = self._read_status(order_id)
        if error:
            return {"valid": False, "errors": [error]}
        if current_status != expected_status:
            return {
                "valid": False,
                "errors": [
                    f"Order {order_id} cannot be reset from expected status "
                    f"'{expected_status}' while its current status is "
                    f"'{current_status}'"
                ],
            }
        return {
            "valid": True,
            "current_status": current_status,
            "new_status": "pending",
        }

    def preview(self, params: dict) -> dict:
        order_id = params["order_id"]
        expected_status = params["expected_status"]
        expected_error = self._validate_expected_status(expected_status)
        if expected_error:
            return {"preview_sql": "N/A", "error": expected_error}

        current_status, error = self._read_status(order_id)
        if error:
            return {"preview_sql": "N/A", "error": error}
        if current_status != expected_status:
            return {
                "preview_sql": "N/A",
                "current_status": current_status,
                "error": (
                    f"Order {order_id} changed to status '{current_status}'; "
                    f"the requested reset expected '{expected_status}'"
                ),
            }
        return {
            "preview_sql": (
                "UPDATE orders SET status = 'pending' "
                "WHERE id = :order_id AND status = :expected_status"
            ),
            "current_status": current_status,
            "new_status": "pending",
            "bound_params": {
                "order_id": order_id,
                "expected_status": current_status,
            },
            "affected_rows_estimate": 1,
            "warnings": [
                f"Demo status will be reset from '{current_status}' to 'pending'"
            ],
            "requires_confirmation": True,
        }

    def build_execution_binding(
        self,
        params: dict,
        validation: dict,
        preview: dict,
    ) -> dict:
        expected_status = params.get("expected_status")
        preview_status = preview.get("current_status")
        if (
            self._validate_expected_status(expected_status) is not None
            or preview_status != expected_status
        ):
            raise ToolError(
                "Preview did not bind the explicitly expected reset source state"
            )
        return {"expected_status": preview_status}

    def execute_with_binding(
        self,
        params: dict,
        execution_binding: dict,
    ) -> dict:
        expected_status = execution_binding.get("expected_status")
        if (
            self._validate_expected_status(expected_status) is not None
            or params.get("expected_status") != expected_status
        ):
            raise ToolError(
                "Missing or mismatched expected reset state from mutation preview"
            )

        order_id = params["order_id"]
        try:
            write_result = self.adapter.execute_write(
                "UPDATE orders SET status = 'pending' "
                "WHERE id = :order_id AND status = :expected_status",
                params={
                    "order_id": order_id,
                    "expected_status": expected_status,
                },
                expected_rowcount=1,
            )
        except ExpectedRowcountMismatchError as error:
            raise MutationWriteError(
                error,
                f"Optimistic lock failed: order {order_id} is no longer "
                f"in expected status '{expected_status}'",
            ) from error
        except WriteExecutionError as error:
            raise MutationWriteError(error) from error
        # Preserve WriteExecutionResult's internal COMMIT evidence while
        # keeping the public mapping shape unchanged.
        write_result.update(
            previous_status=expected_status,
            new_status="pending",
        )
        return write_result

    def execute(self, params: dict) -> dict:
        raise ToolError(
            "Direct unbound execution is disabled; use the preview-token "
            "execution path."
        )
