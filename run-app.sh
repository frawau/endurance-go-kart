#!/bin/sh

# Exit immediately if a command exits with a non-zero status.
set -e

# Check if this is the first run
if [ ! -f /app/.first_run_complete ]; then
  # Apply database migrations
  python manage.py collectstatic --no-input
  python manage.py makemigrations
  python manage.py migrate

  # Create a superuser
  python manage.py createsuperuser_with_password --username ${DJANGO_SUPERUSER_USERNAME} --password ${DJANGO_SUPERUSER_PASSWORD}

  # Create the flag file
  touch /app/.first_run_complete
fi

# Start the Gunicorn server
exec gunicorn --config gunicorn-cfg.py core.asgi
