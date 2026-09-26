"""One explicit configuration entry for service and offline administration."""

import argparse
import json
import logging
import sys
from pathlib import Path
from . import __version__
from .config import ConfigError, explain_config, load_config


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sql-safety-executor")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Run one stdio service process")
    serve.add_argument("--config", required=True, type=Path)
    admin = commands.add_parser("config", help="Offline configuration validation")
    actions = admin.add_subparsers(dest="action", required=True)
    for action in ("check", "explain"):
        sub = actions.add_parser(action)
        sub.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "config":
            if args.action == "check":
                print(
                    "Configuration valid. Database connectivity and Skill implementations were not checked."
                )
            else:
                print(json.dumps(explain_config(config), ensure_ascii=False, indent=2))
            return 0
        settings = config.server.observability.logging
        handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
        if settings.path:
            Path(settings.path).parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(settings.path, encoding="utf-8"))
        logging.basicConfig(
            level=settings.level,
            handlers=handlers,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )
        from .mcp.server import create_server

        server = create_server(config)
        server.run(transport="stdio", show_banner=False, log_level=settings.level)
        return 0
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(
            f"Service failed ({type(exc).__name__}); consult sanitized diagnostics.",
            file=sys.stderr,
        )
        return 1
