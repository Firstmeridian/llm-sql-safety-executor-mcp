"""Reviewed tool annotations and output contracts; prompts contain no policy.

These are code-owned declarations, never deployment configuration.
"""

from typing import Any

TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "list_connections": {
        "annotations": {
            "title": "List Configured Database Connections",
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": False,
        }
    },
    "query": {
        "annotations": {
            "title": "Execute SQL Query",
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": False,
        }
    },
    "check_connection": {
        "output_schema": "$ConnectionReport",
        "annotations": {
            "title": "Check Database Connectivity",
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": False,
        },
    },
    "list_tables": {
        "annotations": {
            "title": "List Visible Database Tables",
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": False,
        }
    },
    "describe_table": {
        "annotations": {
            "title": "Describe Table Structure",
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": False,
        }
    },
    "get_full_schema": {
        "annotations": {
            "title": "Get Visible Database Schema",
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": False,
        }
    },
    "get_table_summary": {
        "annotations": {
            "title": "Get Table Summary with Exact Count",
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": False,
        }
    },
    "sample": {
        "annotations": {
            "title": "Sample Table Data",
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": False,
        }
    },
    "list_skills": {
        "annotations": {
            "title": "List Available Skills",
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": False,
        }
    },
    "get_skill_detail": {
        "annotations": {
            "title": "Get Skill Detail",
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": False,
        }
    },
    "execute_query_skill": {
        "annotations": {
            "title": "Execute Query Skill",
            "read_only_hint": True,
            "destructive_hint": False,
            "idempotent_hint": True,
            "open_world_hint": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "skill_name": {"type": "string"},
                "connection_id": {"type": "string"},
                "db_type": {"type": "string"},
                "data": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": True},
                },
                "row_count": {"type": "integer", "minimum": 0},
                "total_rows": {"type": "integer", "minimum": 0},
                "truncated": {"type": "boolean"},
                "truncation_note": {"type": ["string", "null"]},
            },
            "required": [
                "success",
                "skill_name",
                "data",
                "row_count",
                "total_rows",
                "truncated",
            ],
            "additionalProperties": True,
        },
    },
    "execute_mutation_skill": {
        "annotations": {
            "title": "Execute Mutation Skill",
            "read_only_hint": False,
            "destructive_hint": True,
            "idempotent_hint": False,
            "open_world_hint": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "skill_name": {"type": "string"},
                "mode": {"type": "string", "enum": ["preview", "execute"]},
                "connection_id": {"type": "string"},
                "db_type": {"type": "string"},
                "execution_outcome": {
                    "type": "string",
                    "enum": ["not_executed", "rolled_back", "committed", "unknown"],
                    "description": "Database "
                    "write "
                    "conclusion. "
                    "success "
                    "describes "
                    "tool "
                    "handling; "
                    "for "
                    "a "
                    "managed "
                    "mutation "
                    "this "
                    "field "
                    "describes "
                    "the "
                    "one "
                    "framework-executed "
                    "statement. "
                    "Once "
                    "an "
                    "imperative "
                    "callback "
                    "runs, "
                    "its "
                    "whole-operation "
                    "outcome "
                    "remains "
                    "unknown.",
                },
                "error_code": {
                    "type": "string",
                    "description": "Extensible "
                    "machine-readable "
                    "failure "
                    "code. "
                    "Published "
                    "meanings "
                    "are "
                    "stable; "
                    "unknown "
                    "codes "
                    "never "
                    "authorize "
                    "automatic "
                    "retry.",
                },
                "error": {
                    "type": "string",
                    "description": "Sanitized explanation on structured failures.",
                },
                "preview": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Business "
                    "context "
                    "from the "
                    "Skill. "
                    "For "
                    "managed "
                    "mutations, "
                    "preview_sql "
                    "and "
                    "bound_params "
                    "are "
                    "generated "
                    "by the "
                    "framework "
                    "from the "
                    "cached "
                    "plan and "
                    "final "
                    "preview "
                    "binding.",
                },
                "preview_token": {
                    "type": "string",
                    "description": "API-opaque "
                    "one-time "
                    "bearer "
                    "handle "
                    "returned "
                    "by "
                    "preview "
                    "and "
                    "required "
                    "for "
                    "execute.",
                },
                "preview_token_expires_at": {"type": "string"},
                "result": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Execution "
                    "result; "
                    "typically "
                    "includes "
                    "'rowcount'. "
                    "Shape is "
                    "skill-defined.",
                },
                "validation": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Validation "
                    "details "
                    "when "
                    "success=false "
                    "(contains "
                    "'valid' "
                    "and "
                    "'errors').",
                },
                "idempotent": {"type": "boolean"},
            },
            "required": ["success", "skill_name", "mode", "execution_outcome"],
            "additionalProperties": True,
        },
    },
}
