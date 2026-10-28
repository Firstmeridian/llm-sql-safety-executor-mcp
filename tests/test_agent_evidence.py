"""Portable checks for evidence integrity, not product or model acceptance."""
import json

import pytest

from scripts.validation.agent_evidence import application_bodies, application_observations
from scripts.validation.agent_task_boundaries import REFERENCE, check_query
from scripts.validation.agent_task_boundaries import (
    PAYMENT_BAD_QUERIES, PAYMENT_QUERIES, check_payment_query,
    payment_fixture_cte, payment_truth,
)


def test_identical_batch_results_remain_two_observations():
    body = {"success": True, "data": [{"n": 7}]}
    frames = [{"structuredContent": body, "content": [{"text": json.dumps(body)}]}] * 2
    assert list(application_bodies(frames)) == [body, body]


def test_wait_result_links_to_original_exec_and_preserves_equal_slots():
    body = {"success": True, "mode": "preview", "execution_outcome": "not_executed"}
    events = [
        {"type": "custom_tool_call", "call_id": "e1", "name": "functions.exec",
         "input": "await tools.mcp__sql_safety_executor_mcp__execute_mutation_skill(args)"},
        {"type": "custom_tool_call_output", "call_id": "e1", "output": "Script running with cell ID 7"},
        {"type": "function_call", "call_id": "w1", "name": "functions.wait",
         "arguments": json.dumps({"cell_id": "7"})},
        {"type": "function_call_output", "call_id": "w1", "output": [body, body]},
    ]
    results = application_observations(events)
    assert len(results) == 2
    assert [(r["call_id"], r["output_call_id"], r["slot"]) for r in results] == [
        ("e1", "w1", 0), ("e1", "w1", 1),
    ]


def test_bare_metadata_content_is_observed_but_definition_is_not():
    body = {"success": True, "table_name": "orders", "columns": []}
    events = [
        {"type": "custom_tool_call", "call_id": "e", "name": "exec",
         "input": "await tools.mcp__sql_safety_executor_mcp__describe_table(args)"},
        {"type": "custom_tool_call_output", "call_id": "e",
         "output": [{"type": "input_text", "text": json.dumps(body)}]},
        {"type": "custom_tool_call", "call_id": "d", "name": "exec", "input": "text(ALL_TOOLS)"},
        {"type": "custom_tool_call_output", "call_id": "d", "output": body},
    ]
    assert [r["body"] for r in application_observations(events)] == [body]


def test_repeated_output_is_not_silently_reclassified_as_a_request_count():
    body = {"success": False, "error_code": "unavailable"}
    events = [{"type": "function_call", "call_id": "d", "name": "mcp__sql_safety_executor_mcp__query"}]
    events += [{"type": "function_call_output", "call_id": "d", "output": body}] * 2
    # Without an invocation ledger, equal outputs do not establish call count.
    assert len(application_observations(events)) == 2


def test_temporal_oracle_distinguishes_both_equality_boundaries():
    assert check_query(REFERENCE) == [3, 4, 5]
    assert check_query(REFERENCE.replace("return_date >", "return_date >=")) == [2, 3, 4, 5]
    assert check_query(REFERENCE.replace("rental_date <=", "rental_date <")) == [3, 4]


def test_payment_oracle_covers_scope_multiplicity_zero_refund_and_dates():
    assert payment_truth() == {
        "rental_ids": [1, 4, 8, 9, 10, 11, 13, 14], "rental_count": 8,
        "amount_cents": 2351, "payment_rows": 9, "without_july_payment_ids": [2, 3, 12],
    }
    assert payment_truth(2)["amount_cents"] == 1900
    assert payment_truth(None)["rental_count"] == 9
    assert payment_truth(None)["amount_cents"] == 4251


@pytest.mark.parametrize("sql", PAYMENT_QUERIES.values(), ids=PAYMENT_QUERIES.keys())
def test_payment_scope_accepts_multiple_valid_query_shapes(sql):
    truth = payment_truth()
    assert check_payment_query(sql) == [(truth["rental_count"], truth["amount_cents"])]


@pytest.mark.parametrize("sql", PAYMENT_BAD_QUERIES.values(), ids=PAYMENT_BAD_QUERIES.keys())
def test_payment_matrix_detects_known_wrong_scope_and_aggregation(sql):
    assert check_payment_query(sql) != [(8, 2351)]


def test_inline_payment_fixture_matches_independent_rows_without_creating_objects():
    import sqlite3

    with sqlite3.connect(":memory:") as db:
        for sql in PAYMENT_QUERIES.values():
            # EXISTS already has a WITH clause; combine its additional CTE.
            tail = ", " + sql[5:] if sql.startswith("WITH ") else " " + sql
            actual = db.execute(payment_fixture_cte() + tail, {
                "cutoff": "2005-08-01 00:00:00", "july_start": "2005-07-01 00:00:00", "store_id": 1,
            }).fetchall()
            assert actual == [(8, 2351)]
        assert db.execute("SELECT COUNT(*) FROM sqlite_schema").fetchone() == (0,)
