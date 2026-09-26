"""Shared preparation/execution boundary for manual and MRTR interactions."""

from .mutations import execute_mutation_skill


class MutationService:
    def __init__(self, runtime):
        self.runtime = runtime

    async def prepare(self, skill_name, params, ctx, connection_id=None):
        return await execute_mutation_skill(
            self.runtime, skill_name, params, ctx, connection_id=connection_id
        )

    async def execute(self, skill_name, params, ctx, preview_token, connection_id=None):
        return await execute_mutation_skill(
            self.runtime,
            skill_name,
            params,
            ctx,
            confirm=True,
            preview_token=preview_token,
            connection_id=connection_id,
        )
