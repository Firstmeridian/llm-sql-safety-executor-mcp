#!/usr/bin/env python3
"""Run a read through the same complete policy used by MCP tools."""

import argparse
import asyncio
import json
from sql_safety_executor import load_config
from sql_safety_executor.core.runtime import GatewayRuntime
from sql_safety_executor.core.queries import query
from sql_safety_executor.core.types import NullContext


async def main(args):
    runtime = GatewayRuntime(load_config(args.config))
    try:
        result = await query(runtime, args.sql, NullContext(), args.connection_id)
        print(json.dumps(result.structured_content, ensure_ascii=False, indent=2))
    finally:
        runtime.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--connection-id")
    parser.add_argument("sql")
    asyncio.run(main(parser.parse_args()))
