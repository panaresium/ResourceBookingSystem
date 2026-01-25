#!/bin/bash
set -e

# Default to 8080 if PORT not set
PORT=${PORT:-8080}

echo "INFO: Starting docker-entrypoint.sh..."

# Run database migrations
echo "INFO: Attempting database migrations..."
# We allow this to fail (e.g. if DB is empty or fresh),
# because the app logic now redirects to /setup which handles initialization (db.create_all).
# OR if migrations are just applying updates to an existing schema.
if flask db upgrade; then
    echo "INFO: Database migrations completed successfully."
else
    echo "WARNING: Database migrations failed. This is expected if the database is fresh. The application will redirect to the Setup page to initialize the schema."
fi

# We skip seed_data.py here because the Setup page handles creating the Admin/Roles explicitly.
# If you want auto-seeding for existing DBs, you could keep it, but it might conflict with the Setup flow logic.
# For now, let's rely on the Setup page for the "clean slate" experience.

# Start Gunicorn
echo "INFO: Starting Gunicorn on 0.0.0.0:$PORT..."
exec gunicorn --workers 2 --threads 4 --worker-class gthread \
    --bind 0.0.0.0:$PORT \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    wsgi:app
