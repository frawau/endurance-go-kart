# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

from django.contrib import admin

from django.apps import apps
from django.contrib import admin
from .models import Logo

# Register your models here.


@admin.register(Logo)
class LogoAdmin(admin.ModelAdmin):
    list_display = ("name", "championship", "image")
    list_filter = ("championship",)
    search_fields = ("name",)


app_models = apps.get_app_config("race").get_models()
for model in app_models:
    try:

        # Special processing for UserProfile
        if "UserProfile" == model.__name__:

            # The model is registered only if has specific data
            # 1 -> ID
            # 2 -> User (one-to-one) relation
            if len(model._meta.fields) > 2:
                admin.site.register(model)

        # Register to Admin
        elif model.__name__ != "Logo":
            admin.site.register(model)

    except Exception:
        pass
