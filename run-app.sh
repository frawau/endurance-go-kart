#!/bin/sh

# Exit immediately if a command exits with a non-zero status.
set -e

# Apply database migrations
python manage.py makemigrations
python manage.py migrate

# Generate initial data

# Create a superuser
python manage.py createsuperuser_with_password --username ${DJANGO_SUPERUSER_USERNAME} --password ${DJANGO_SUPERUSER_PASSWORD}

# Start the Gunicorn server
exec gunicorn --config gunicorn-cfg.py core.asgi
