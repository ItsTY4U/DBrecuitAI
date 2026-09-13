#!/bin/sh
set -e

# Wait for database if DB_HOST and DB_PORT are provided
if [ -n "$DB_HOST" ] && [ -n "$DB_PORT" ]; then
    echo "Waiting for database at $DB_HOST:$DB_PORT..."
    MAX_RETRIES=30
    COUNT=0
    while ! nc -z "$DB_HOST" "$DB_PORT"; do
        COUNT=$((COUNT + 1))
        if [ "$COUNT" -ge "$MAX_RETRIES" ]; then
            echo "Warning: Database at $DB_HOST:$DB_PORT is not reachable yet after ${MAX_RETRIES}s. Proceeding anyway..."
            break
        fi
        sleep 1
    done
    if [ "$COUNT" -lt "$MAX_RETRIES" ]; then
        echo "Database is reachable."
    fi
fi

# Apply database migrations
if [ "$SKIP_MIGRATIONS" != "1" ]; then
    echo "Applying database migrations..."
    python manage.py migrate --noinput
fi

# Collect static files if enabled or in production
if [ "$COLLECT_STATIC" = "1" ] || [ -z "$DEBUG" ] || [ "$DEBUG" = "False" ]; then
    echo "Collecting static files..."
    python manage.py collectstatic --noinput
fi

exec "$@"