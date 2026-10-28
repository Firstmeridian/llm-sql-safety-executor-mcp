"""Check the published demo lifecycle against real previews, with independent truth."""

from datetime import datetime
import sqlite3

from fastmcp import Client
import pytest

from sql_safety_executor import create_server, load_config
from tests.test_v38_config import bundle as bundle


# Deliberately independent of the demo module's VALID_TRANSITIONS constant.
STATES = ("pending", "confirmed", "shipped", "delivered", "cancelled", "returned")
EDGES = {
    ("pending", "confirmed"), ("pending", "cancelled"),
    ("confirmed", "shipped"), ("confirmed", "cancelled"),
    ("shipped", "delivered"), ("shipped", "returned"),
    ("delivered", "returned"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_catalog_lifecycle_matches_all_preview_transitions(bundle, mode):
    _, connections, _, save = bundle
    connections["connections"]["demo"]["read"] = {
        "mode": "allowlist", "tables": ["orders"],
    }
    connections["connections"]["demo"]["mutation"] = {
        "enabled": True, "skills": ["sample-update-order-status"],
    }
    config = load_config(save(use_skills=True))
    database = config.connections["demo"].sqlite_database_path
    initial = list(enumerate(STATES, start=1))
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE orders(id INTEGER PRIMARY KEY, status TEXT)")
        db.executemany("INSERT INTO orders VALUES(?, ?)", initial)
    server = create_server(config)
    try:
        async with Client(server, mode=mode) as client:
            descriptions = []
            for level in ("compact", "summary", "full"):
                result = await client.call_tool("list_skills", {
                    "connection_id": "demo", "available_only": False,
                    "detail_level": level,
                })
                assert result.structured_content["success"] is True
                skill = next(s for s in result.structured_content["skills"]
                             if s["name"] == "sample-update-order-status")
                descriptions.append(skill["description"])
            result = await client.call_tool("get_skill_detail", {
                "connection_id": "demo", "skill_name": "sample-update-order-status",
                "detail_level": "full",
            })
            descriptions.append(result.structured_content["skill"]["description"])
            assert len(set(descriptions)) == 1
            description = descriptions[0]
            assert "one step along pending to confirmed to shipped to delivered" in description
            assert "cancelled is allowed only from pending or confirmed" in description
            assert "returned only from shipped or delivered" in description
            assert "terminal states with no outgoing transitions" in description

            for order_id, before in initial:
                for after in STATES:
                    result = await client.call_tool("execute_mutation_skill", {
                        "connection_id": "demo", "skill_name": "sample-update-order-status",
                        "params": {"order_id": order_id, "new_status": after},
                        "confirm": False,
                    })
                    payload = result.structured_content
                    assert payload["execution_outcome"] == "not_executed"
                    assert payload["success"] is ((before, after) in EDGES), (before, after, payload)
                    if (before, after) in EDGES:
                        assert payload["preview"]["current_status"] == before
                        assert payload["preview_token"]
                        expiry = datetime.fromisoformat(payload["preview_token_expires_at"])
                        assert expiry.utcoffset() is not None
                    else:
                        assert payload["error_code"] == "validation_failed"
                        assert "preview_token" not in payload
                    # Separate native connection; do not reuse the tested adapter.
                    with sqlite3.connect(database) as db:
                        assert db.execute("SELECT id, status FROM orders ORDER BY id").fetchall() == initial
            assert len(server.gateway_runtime.tokens) == len(EDGES)
    finally:
        server.gateway_runtime.close()
