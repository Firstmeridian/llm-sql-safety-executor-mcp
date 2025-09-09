#!/usr/bin/env python3
"""
Startup script for SQL Safety MCP Server

This script provides an easy way to start the MCP server with proper configuration
and error handling.
"""

import sys
import os
import logging
from pathlib import Path

# Add the current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

def check_dependencies():
    """Check if all required dependencies are installed"""
    required_modules = [
        ('mcp', 'Model Context Protocol'),
        ('sqlparse', 'SQL Parser'),
        ('sqlalchemy', 'SQLAlchemy ORM'),
        ('mysql.connector', 'MySQL Connector'),
        ('dotenv', 'Python Dotenv')
    ]
    
    missing_modules = []
    for module_name, description in required_modules:
        try:
            __import__(module_name)
        except ImportError:
            missing_modules.append((module_name, description))
    
    if missing_modules:
        print("❌ Missing required dependencies:")
        for module_name, description in missing_modules:
            print(f"   • {module_name} ({description})")
        print("\n💡 Install dependencies with: pip install -r requirements.txt")
        return False
    
    return True

def check_configuration():
    """Check if configuration is properly set up"""
    from server_config import config
    
    print("📋 Server Configuration:")
    print(f"   • Server Name: {config.server_name}")
    print(f"   • Server Version: {config.server_version}")
    print(f"   • Log Level: {config.log_level}")
    
    if config.is_database_configured():
        print(f"   • Database: ✅ Configured ({config.db_host}/{config.db_name})")
    else:
        print("   • Database: ⚠️  Not configured (SQL execution will show errors)")
        print("     Create .env file with DB_USER, DB_PASSWORD, DB_HOST, DB_NAME")
    
    return True

def start_server():
    """Start the MCP server"""
    try:
        from mcp_server import main
        import asyncio
        
        print("\n🚀 Starting SQL Safety MCP Server...")
        print("   Use Ctrl+C to stop the server")
        print("=" * 50)
        
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped by user")
    except Exception as e:
        print(f"\n❌ Error starting server: {e}")
        return False
    
    return True

def main():
    """Main startup function"""
    print("🔧 SQL Safety MCP Server Startup")
    print("=" * 40)
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    print("✅ All dependencies are installed")
    
    # Check configuration
    if not check_configuration():
        sys.exit(1)
    
    # Start the server
    if not start_server():
        sys.exit(1)

if __name__ == "__main__":
    main()