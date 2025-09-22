#!/usr/bin/env python3
"""
MCP Server Startup Script

This script starts the SQL Safety Checker MCP server with proper environment
validation and logging configuration.
"""

import os
import logging
from dotenv import load_dotenv
from mcp_sql_server import mcp
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

# 0917 Add logs directory
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)
# New file name with time
log_filename = f"{log_dir}/sql_safety_checker_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),  # to file
        # logging.StreamHandler()             # to console
    ]
)
logger = logging.getLogger(__name__)

def validate_environment():
    """
    Validates that all required environment variables are set.
    
    Returns:
        tuple: (is_valid, missing_vars)
    """
    required_env_vars = ["DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    return len(missing_vars) == 0, missing_vars

def main():
    """Main function to start the MCP server with validation."""
    logger.info("=== SQL Safety Checker MCP Server ===")
    logger.info(f"Log file: {log_filename}") # 0917 Log file path
    logger.info("Initializing server startup...")
    
    # Validate environment configuration
    is_valid, missing_vars = validate_environment()
    
    if not is_valid:
        logger.error(f"Missing required environment variables: {missing_vars}")
        logger.error("Please ensure your .env file is configured correctly")
        logger.error("Required variables: DB_USER, DB_PASSWORD, DB_HOST, DB_NAME")
        return 1
    
    logger.info("Environment validation passed")
    logger.info("Starting MCP server...")
    
    try:
        # Run the MCP server
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Server shutdown requested by user")
        return 0
    except Exception as e:
        logger.error(f"Server error: {e}")
        return 1

if __name__ == "__main__":
    exit(main())