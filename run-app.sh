#!/bin/bash

# Wait for postgres to be ready
echo "Waiting for postgres..."
while ! nc -z postgres 5432; do
  sleep 0.1
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