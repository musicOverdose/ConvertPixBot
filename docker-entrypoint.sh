#!/usr/bin/env bash
set -e

# Ensure required directories exist
mkdir -p /data /tmp/bot-app

# By default, runs as current user (root in container) to guarantee read access to
# external shared volumes (e.g. telegram-bot-api-data).
# If unprivileged execution is explicitly requested, set DROP_PRIVILEGES=true or specify BOT_USER.
if [ -n "$BOT_USER" ]; then
    chown -R "$BOT_USER" /data /tmp/bot-app 2>/dev/null || true
    exec gosu "$BOT_USER" "$@"
elif [ "$DROP_PRIVILEGES" = "true" ]; then
    chown -R botuser:botgroup /data /tmp/bot-app 2>/dev/null || true
    exec gosu botuser "$@"
fi

exec "$@"
