"""
ASGI config for core project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.1/howto/deployment/asgi/
"""
import os
import django
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

# Initialize Django setup
django.setup()

# Initialize Django ASGI application first
django_asgi_app = get_asgi_application()

# Now import Django-dependent modules after Django is initialized
from channels.routing import ProtocolTypeRouter, URLRouter
from race import routing

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": URLRouter(routing.websocket_urlpatterns),
    }
)
