#!/bin/bash

# Wait for postgres to be ready
echo "Waiting for postgres..."
until python -c "
import socket
import sys
import time
print('Checking PostgreSQL connection...', flush=True)
try:
    sock = socket.create_connection(('postgres', 5432), timeout=5)
    sock.close()
    print('PostgreSQL connection successful!', flush=True)
    sys.exit(0)
except Exception as e:
    print(f'PostgreSQL not ready: {e}', flush=True)
    sys.exit(1)
"; do
  echo "PostgreSQL not ready, waiting..."
  sleep 2
done
echo "PostgreSQL started"

# Always run collectstatic (safe to run multiple times)
echo "Collecting static files..."
python manage.py collectstatic --no-input

# Check if first-run setup has been completed
if [ ! -f /app/.first_run_complete ]; then
    echo "First run detected - running initial setup..."
    python manage.py makemigrations
    python manage.py migrate
    python manage.py createsuperuser_with_password --username ${DJANGO_SUPERUSER_USERNAME} --password ${DJANGO_SUPERUSER_PASSWORD}

    # Mark first run as complete
    touch /app/.first_run_complete
    echo "First run setup complete"
else
    echo "Checking for new migrations..."
    python manage.py makemigrations
    python manage.py migrate
fi

# Start the application
echo "Starting Gunicorn..."
exec gunicorn --config gunicorn-cfg.py core.asgi