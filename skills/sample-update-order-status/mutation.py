"""
Mutation skill: sample-update-order-status

Safely updates an order's status with state machine constraints.
Uses optimistic locking to prevent concurrent conflicting updates.
"""

from fastmcp.exceptions import ToolError
from mutation_base import (  # type: ignore[import-not-found]
    ManagedMutationBase,
    ManagedMutationPlan,
    ManagedMutationValue,
)


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


class Mutation(ManagedMutationBase):
    """Update order status with state machine validation."""

    managed_plan = ManagedMutationPlan(
        sql=(
            "UPDATE orders SET status = :new_status "
            "WHERE id = :order_id AND status = :expected_status"
        ),
        parameters=(
            ManagedMutationValue.from_params("new_status"),
            ManagedMutationValue.from_params("order_id"),
            ManagedMutationValue.from_binding("expected_status"),
        ),
        expected_rowcount=1,
        result_fields=(
            ManagedMutationValue.from_binding("previous_status", "expected_status"),
            ManagedMutationValue.from_params("new_status"),
        ),
    )

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

        Returns business context; the framework adds SQL and bound parameters.
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
                "error": f"Order {order_id} not found or query failed",
            }

        current_status = result[0].status  # type: ignore[union-attr]
        allowed = VALID_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            return {
                "current_status": current_status,
                "error": (
                    f"Order {order_id} changed to status '{current_status}'; "
                    f"transition to '{new_status}' is no longer allowed"
                ),
            }

        return {
            "current_status": current_status,
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
        expected_status = preview.get("current_status")
        if not isinstance(expected_status, str) or not expected_status:
            raise ToolError("Preview did not produce a valid expected order status")
        return {"expected_status": expected_status}
