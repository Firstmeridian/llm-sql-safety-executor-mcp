FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY sql_safety_checker.py .
COPY mcp_sql_server.py .
COPY .env* ./

# Expose port for HTTP mode (if needed)
EXPOSE 8000

# Default command
CMD ["python", "mcp_sql_server.py"]