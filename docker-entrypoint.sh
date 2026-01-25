#!/bin/bash
set -e

# Default to 8080 if PORT not set
PORT=${PORT:-8080}

echo "INFO: Starting docker-entrypoint.sh..."

# Run database migrations
echo "INFO: Attempting database migrations..."
if flask db upgrade; then
    echo "INFO: Database migrations completed successfully."
else
    echo "WARNING: Database migrations failed. This is expected if the database is fresh or connection issues exist."
    echo "WARNING: The application will redirect to the /setup page to initialize the schema and admin user."
fi

# Start Gunicorn
echo "INFO: Starting Gunicorn on 0.0.0.0:$PORT..."
exec gunicorn --workers 2 --threads 4 --worker-class gthread \
    --bind 0.0.0.0:$PORT \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    wsgi:app
