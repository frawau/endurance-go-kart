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
from channels.auth import AuthMiddlewareStack

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

# Initialize Django before importing anything that uses models
django.setup()

# Now safe to import routing
from race import routing

# AuthMiddlewareStack populates scope["user"] from the session cookie so
# consumers can enforce authentication/authorization. It rejects no one on
# its own — operator consumers check scope["user"] in connect(), and the
# browser-facing routes are additionally origin-validated in routing.py.
# Native station daemons (timing, stop-and-go) connect without a session and
# are authenticated by HMAC instead.
application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        "websocket": AuthMiddlewareStack(URLRouter(routing.websocket_urlpatterns)),
    }
)
