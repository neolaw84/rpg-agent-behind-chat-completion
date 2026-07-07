# Use an official Python 3.12 slim image as parent
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860 \
    RPG_AGENT_STATE_DIR=/app/data/states \
    RPG_AGENT_KEY_FILE=/app/data/proxy.key \
    RPG_AGENT_CONFIG_PATH=/app/configs.yaml \
    RPG_AGENT_SANDBOX_ENGINE=v8

# Set work directory
WORKDIR /app

# Copy files
COPY pyproject.toml configs.yaml README.md ./
COPY src/ ./src/

# Install project and dependencies
RUN pip install --no-cache-dir .

# Create a non-root user (UID 1000) for security and Hugging Face compatibility
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data/states && \
    chown -R appuser:appuser /app

# Switch to the non-root user
USER appuser

# Expose the default port (can be overridden by environment variable PORT)
EXPOSE 7860

# Run the proxy CLI
CMD ["rpg-agent-proxy"]
