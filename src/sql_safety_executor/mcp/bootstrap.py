"""Disable framework dotenv discovery before its first import."""

import os


def prepare_framework() -> None:
    # This is a framework bootstrap option, never a database configuration
    # channel. An embedding Host that imported FastMCP earlier owns that import.
    os.environ["FASTMCP_ENV_FILE"] = os.devnull
