"""SQL safety executor. Importing this package has no deployment side effects."""

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from .config import AppConfig

__version__ = "3.8.0"


def create_server(config: "AppConfig") -> "FastMCP":
    """Build an isolated server from an explicitly loaded AppConfig."""
    from .mcp.server import create_server as factory

    return factory(config)


def load_config(path: str | Path) -> "AppConfig":
    """Validate a deployment without accessing its databases or Skill sources."""
    from .config import load_config as loader

    return loader(path)
