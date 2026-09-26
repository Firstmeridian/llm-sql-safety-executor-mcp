"""Keep deprecated legacy logging notifications out of modern protocol calls."""

import logging

logger = logging.getLogger(__name__)


class ToolContext:
    def __init__(self, context):
        self.context = context

    @property
    def client_id(self):
        return getattr(self.context, "client_id", None)

    async def _log(self, level: str, message: str):
        request = self.context.request_context
        if request is not None and request.protocol_version == "2026-07-28":
            logger.log(getattr(logging, level.upper()), message)
        else:
            await getattr(self.context, level)(message)

    async def info(self, message: str):
        await self._log("info", message)

    async def warning(self, message: str):
        await self._log("warning", message)

    async def error(self, message: str):
        await self._log("error", message)
