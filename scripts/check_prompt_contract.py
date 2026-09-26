#!/usr/bin/env python3
"""Validate installed prompt resources without opening a database."""

import argparse
from sql_safety_executor import load_config
from sql_safety_executor.prompts.render import assistant, instructions

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    config = load_config(parser.parse_args().config)
    for prompt in (assistant(config), instructions(config)):
        assert "connection_id" in prompt
        assert "list_connections" in prompt
    assert "UNION policy is connection-specific" in assistant(config)
    print("Installed prompt resources and routing guidance valid.")
