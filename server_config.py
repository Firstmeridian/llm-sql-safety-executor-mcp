#!/usr/bin/env python3
"""
Configuration for SQL MCP Server

This module provides configuration management for the MCP server.
"""

import os
from typing import Optional
from dataclasses import dataclass


@dataclass
class ServerConfig:
    """Configuration for the SQL MCP Server"""
    
    # Server settings
    server_name: str = "sql-safety-server"
    server_version: str = "1.0.0"
    
    # Database settings
    db_user: Optional[str] = None
    db_password: Optional[str] = None
    db_host: Optional[str] = None
    db_name: Optional[str] = None
    
    # Logging settings
    log_level: str = "INFO"
    
    def __post_init__(self):
        """Load configuration from environment variables"""
        self.db_user = os.getenv("DB_USER", self.db_user)
        self.db_password = os.getenv("DB_PASSWORD", self.db_password)
        self.db_host = os.getenv("DB_HOST", self.db_host)
        self.db_name = os.getenv("DB_NAME", self.db_name)
        self.log_level = os.getenv("LOG_LEVEL", self.log_level)
    
    @property
    def database_url(self) -> Optional[str]:
        """Generate database URL if all required fields are present"""
        if all([self.db_user, self.db_password, self.db_host, self.db_name]):
            return f"mysql+mysqlconnector://{self.db_user}:{self.db_password}@{self.db_host}/{self.db_name}"
        return None
    
    def is_database_configured(self) -> bool:
        """Check if database is properly configured"""
        return self.database_url is not None


# Global configuration instance
config = ServerConfig()