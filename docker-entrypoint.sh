#!/bin/bash
set -e

# Run database migrations
echo "Running database migrations..."
flask db upgrade

# Seed initial data
echo "Seeding initial data..."
python seed_data.py

# Start Gunicorn
echo "Starting Gunicorn..."
# Bind to 0.0.0.0:8080 as required by Cloud Run
exec gunicorn --workers 2 --threads 4 --worker-class gthread --bind 0.0.0.0:8080 --timeout 600 wsgi:app
