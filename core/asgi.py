"""
ASGI config for core project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.1/howto/deployment/asgi/
"""
import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

# Initialize Django before importing anything that uses models
django.setup()

# Now safe to import routing
from race import routing

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": URLRouter(routing.websocket_urlpatterns),
    }
)
