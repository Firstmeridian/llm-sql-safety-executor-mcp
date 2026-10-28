"""Small public-evidence helpers, not protocol capture or an Agent grader.

Results are observations, not request counts: two identical results in one batch
must survive, and a repeated output cannot prove another request was sent.
"""
from __future__ import annotations

import json
import re


def application_bodies(value):
    """Prefer structured content; retain distinct slots even when values equal."""
    if isinstance(value, dict):
        for key in ("structuredContent", "structured_content"):
            if isinstance(value.get(key), dict):
                yield value[key]
                return
        if isinstance(value.get("success"), bool):
            yield value
            return
        for child in value.values():
            yield from application_bodies(child)
    elif isinstance(value, list):
        for child in value:
            yield from application_bodies(child)
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (ValueError, RecursionError):
            return
        yield from application_bodies(decoded)


def application_observations(events):
    """Associate yielded exec/wait outputs without payload-based deduplication.

    Input is already filtered public events. Request counts require a separate
    invocation ledger or call-code audit; this function deliberately returns no
    request-count field. It does not collect or redact source session logs.
    """
    calls, cells, observations = {}, {}, []
    for event in events:
        kind = event.get("type")
        call_id = event.get("call_id")
        if kind in {"function_call", "custom_tool_call"}:
            calls[call_id] = event
            continue
        if kind not in {"function_call_output", "custom_tool_call_output"}:
            continue
        source_id = call_id
        call = calls.get(call_id, {})
        if call.get("name", "").rsplit(".", 1)[-1] == "wait":
            args = call.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            if isinstance(args, dict):
                source_id = cells.get(str(args.get("cell_id")), call_id)
        call = calls.get(source_id, {})
        output = event.get("output")
        for cell in re.findall(r"Script running with cell ID ([A-Za-z0-9_-]+)", str(output)):
            cells[cell] = source_id
        code = str(call.get("input", call.get("arguments", "")))
        direct = call.get("name", "").startswith("mcp__sql_safety_executor_mcp__")
        if not direct and "tools.mcp__sql_safety_executor_mcp__" not in code:
            continue
        for slot, body in enumerate(application_bodies(output)):
            observations.append({"call_id": source_id, "output_call_id": call_id,
                                 "slot": slot, "body": body})
    return observations
