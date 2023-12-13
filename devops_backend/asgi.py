"""
ASGI config for devops_backend project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.2/howto/deployment/asgi/
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'devops_backend.settings')
django.setup()
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

from channels.auth import AuthMiddlewareStack
import deploy.routing

django_application = get_asgi_application()

application = ProtocolTypeRouter({
    # Explicitly set 'http' key using Django's ASGI application.
    "http": django_application,
    'websocket': AuthMiddlewareStack(
        URLRouter(
            deploy.routing.websocket_urlpatterns
        )
    ),
})
