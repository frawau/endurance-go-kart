# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.contrib import admin
from django.urls import path, re_path, include
from django.contrib.auth import views as auth_views
from race.routing import websocket_urlpatterns
from channels.routing import URLRouter

try:
    from rest_framework.authtoken.views import obtain_auth_token
except:
    pass

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("race.urls")),
    # path("", include("theme_material_kit.urls")),
    path("login/jwt/", view=obtain_auth_token),
    path("accounts/", include("django.contrib.auth.urls")),
    # re_path(r"^advanced_filters/", include("advanced_filters.urls")),
]


# Lazy-load on routing is needed
# During the first build, API is not yet generated
try:
    urlpatterns.append(path("", include("django_dyn_api.urls")))
    urlpatterns.append(path("login/jwt/", view=obtain_auth_token))
except:
    pass
