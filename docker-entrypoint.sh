#!/bin/bash
set -e

# Default to 8080 if PORT not set
PORT=${PORT:-8080}

echo "INFO: Starting docker-entrypoint.sh..."

# Run database migrations
echo "INFO: Running database migrations..."
if flask db upgrade; then
    echo "INFO: Database migrations completed successfully."
else
    echo "ERROR: Database migrations failed."
    exit 1
fi

# Seed initial data
echo "INFO: Seeding initial data..."
if python seed_data.py; then
    echo "INFO: Initial data seeding completed successfully."
else
    echo "ERROR: Initial data seeding failed."
    exit 1
fi

# Start Gunicorn
echo "INFO: Starting Gunicorn on 0.0.0.0:$PORT..."
# Using --access-logfile - and --error-logfile - to ensure logs go to stdout/stderr for Cloud Logging
exec gunicorn --workers 2 --threads 4 --worker-class gthread \
    --bind 0.0.0.0:$PORT \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    wsgi:app
