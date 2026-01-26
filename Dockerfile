FROM python:3.10-slim

# Install system dependencies
# libpq-dev and gcc are needed for psycopg2 compilation (if binary not used, but binary is preferred for simplicity)
# curl for health checks if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make entrypoint executable
RUN chmod +x docker-entrypoint.sh

# Environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py

# Expose port
EXPOSE 8080

# Entrypoint
ENTRYPOINT ["./docker-entrypoint.sh"]
