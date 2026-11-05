"""Explicit per-kind Skill publication; deployment settings remain fixed."""

import time
from typing import Annotated, Literal

import anyio
from pydantic import Field

from sql_safety_executor.core.results import _tool_result
from sql_safety_executor.core.types import OperationContext as Context
from sql_safety_executor.skills.catalog import SkillReloadError


async def reload_skills(
    runtime,
    ctx: Context,
    skill_type: Annotated[
        Literal["query", "mutation"],
        Field(description="Skill kind to publish. Query (default) preserves Mutation code and previews. Mutation imports trusted Python entries and invalidates affected pending previews."),
    ] = "query",
):
    """Reload one kind of Skill from the configured directory."""
    start = time.perf_counter()
    try:
        payload = await anyio.to_thread.run_sync(runtime.reload_skills, skill_type)
    except (SkillReloadError, OSError, UnicodeError) as exc:
        payload = {
            "success": False,
            "error_code": f"{skill_type}_reload_failed",
            "skill_type": skill_type,
            "reason": exc.reason if isinstance(exc, SkillReloadError) else "candidate_files_unavailable",
            "skill_name": exc.skill_name if isinstance(exc, SkillReloadError) else None,
            "revision": runtime.catalog_revision,
            "hint": "The previous catalog and pending previews remain active. Correct the candidate files before requesting another publication. Shared Python dependencies and deployment configuration require restart.",
        }
    return _tool_result(runtime, payload, tool_name="reload_skills", start_time=start,
                        connection_scope="all", success=payload["success"])
