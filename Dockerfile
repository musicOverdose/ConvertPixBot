# Multi-stage / optimized Debian slim container for MusicOverdose Bot
FROM python:3.13-slim-bookworm

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Install system dependencies: ffmpeg, media libraries, ca-certificates, gosu
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libmagic1 \
    ca-certificates \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root user and group, plus group 101 for telegram-bot-api volume compatibility
RUN groupadd -g 10001 botgroup && \
    groupadd -g 101 tgapi && \
    useradd -u 10001 -g botgroup -G tgapi -s /bin/bash -m botuser

# Set working directory
WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY app/ ./app/

# Create CLI executable wrapper in PATH
RUN echo '#!/usr/bin/env bash\nexec python -m app.cli "$@"' > /usr/local/bin/cli && \
    chmod +x /usr/local/bin/cli

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create and set permissions on data and temporary directories
RUN mkdir -p /data /tmp/bot-app && \
    chown -R botuser:botgroup /data /tmp/bot-app /app

# Entrypoint initializes directories and runs the application
ENTRYPOINT ["docker-entrypoint.sh"]

# Default command starts the bot in long polling mode
CMD ["python", "-m", "app.main"]
