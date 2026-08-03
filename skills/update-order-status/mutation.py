"""
Mutation skill: update-order-status

Safely updates an order's status with state machine constraints.
Uses optimistic locking to prevent concurrent conflicting updates.
"""

from fastmcp.exceptions import ToolError
from mutation_base import MutationBase  # type: ignore[import-not-found]


# Valid state transitions (from -> allowed to states)
VALID_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["confirmed", "cancelled"],
    "confirmed": ["shipped", "cancelled"],
    "shipped": ["delivered", "returned"],
    "delivered": ["returned"],
    # Terminal states — no outgoing transitions
    "cancelled": [],
    "returned": [],
}


class Mutation(MutationBase):
    """Update order status with state machine validation."""

    def validate(self, params: dict) -> dict:
        """
        Validate that the requested status transition is allowed.

        Checks:
        1. new_status is a valid status value
        2. The order exists
        3. Current status allows transition to new_status
        """
        errors = []
        order_id = params["order_id"]
        new_status = params["new_status"]

        # Check new_status is in the transition table
        all_statuses = set(VALID_TRANSITIONS.keys())
        if new_status not in all_statuses:
            errors.append(
                f"Invalid status '{new_status}'. "
                f"Valid: {sorted(all_statuses)}"
            )
            return {"valid": False, "errors": errors}

        # Look up current order status
        result = self.adapter.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": order_id},
        )

        if isinstance(result, str) and result.startswith("Error:"):
            errors.append(f"Database error: {result}")
            return {"valid": False, "errors": errors}

        if not result:
            errors.append(f"Order {order_id} not found")
            return {"valid": False, "errors": errors}

        current_status = result[0].status  # type: ignore[union-attr]

        # Check transition is allowed
        allowed = VALID_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            if not allowed:
                errors.append(
                    f"Order {order_id} is in terminal state "
                    f"'{current_status}' — no transitions allowed"
                )
            else:
                errors.append(
                    f"Transition from '{current_status}' to '{new_status}' "
                    f"is not allowed. Allowed: {allowed}"
                )
            return {"valid": False, "errors": errors}

        return {
            "valid": True,
            "current_status": current_status,
            "new_status": new_status,
        }

    def preview(self, params: dict) -> dict:
        """
        Preview the mutation without making changes.

        Returns the SQL that would be executed and the expected effect.
        """
        order_id = params["order_id"]
        new_status = params["new_status"]

        # Get current status for preview display
        result = self.adapter.execute(
            "SELECT id, status FROM orders WHERE id = :order_id",
            params={"order_id": order_id},
        )

        if not result or (isinstance(result, str) and result.startswith("Error:")):
            return {
                "preview_sql": "N/A",
                "error": f"Order {order_id} not found or query failed",
            }

        current_status = result[0].status  # type: ignore[union-attr]

        return {
            "preview_sql": (
                "UPDATE orders SET status = :new_status "
                "WHERE id = :order_id AND status = :expected_status"
            ),
            "bound_params": {
                "new_status": new_status,
                "order_id": order_id,
                "expected_status": current_status,
            },
            "affected_rows_estimate": 1,
            "warnings": [
                f"Status will change from '{current_status}' to '{new_status}'"
            ],
            "requires_confirmation": True,
        }

    def build_execution_binding(
        self,
        params: dict,
        validation: dict,
        preview: dict,
    ) -> dict:
        """Bind execute to the order status shown during preview."""
        expected_status = validation.get("current_status")
        if not isinstance(expected_status, str) or not expected_status:
            raise ToolError("Preview did not produce a valid expected order status")
        return {"expected_status": expected_status}

    def execute_with_binding(
        self,
        params: dict,
        execution_binding: dict,
    ) -> dict:
        """Execute only if the status still matches the previewed state."""
        expected_status = execution_binding.get("expected_status")
        if not isinstance(expected_status, str) or not expected_status:
            raise ToolError("Missing expected order status from mutation preview")
        return self._execute_with_expected_status(params, expected_status)

    def execute(self, params: dict) -> dict:
        """
        Execute the status update within a transaction.

        Uses optimistic locking: WHERE status = :expected_status
        ensures no concurrent modification has occurred.
        """
        order_id = params["order_id"]
        new_status = params["new_status"]

        # Get current status for optimistic lock
        result = self.adapter.execute(
            "SELECT status FROM orders WHERE id = :order_id",
            params={"order_id": order_id},
        )

        if not result or (isinstance(result, str) and result.startswith("Error:")):
            raise ToolError(f"Order {order_id} not found or query failed")

        current_status = result[0].status  # type: ignore[union-attr]

        return self._execute_with_expected_status(params, current_status)

    def _execute_with_expected_status(
        self,
        params: dict,
        expected_status: str,
    ) -> dict:
        """Apply the update using the previewed status as the lock value."""
        order_id = params["order_id"]
        new_status = params["new_status"]

        # Execute the update with optimistic locking
        write_result = self.adapter.execute_write(
            "UPDATE orders SET status = :new_status "
            "WHERE id = :order_id AND status = :expected_status",
            params={
                "new_status": new_status,
                "order_id": order_id,
                "expected_status": expected_status,
            },
        )

        if write_result["rowcount"] == 0:
            raise ToolError(
                f"Optimistic lock failed: order {order_id} status has "
                f"changed from '{expected_status}' (concurrent modification)"
            )

        return {
            "success": True,
            "rowcount": write_result["rowcount"],
            "previous_status": expected_status,
            "new_status": new_status,
        }
