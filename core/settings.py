# -*- encoding: utf-8 -*-
"""
Copyright (c) 2019 - present AppSeed.us
"""

import os, random, string
from pathlib import Path
from dotenv import load_dotenv

from helpers import *

load_dotenv()  # LOAD variables from .env

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/4.1/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("SECRET_KEY", "TODO_SET_SECRET_KEY" )

# Stop and Go Station HMAC Secret
STOPANDGO_HMAC_SECRET = os.environ.get(
    "STOPANDGO_HMAC_SECRET", "race_control_hmac_key_2024"
)

DEBUG = os.environ.get("DEBUG", True)
APP_DOMAIN = os.getenv("APP_DOMAIN", "gokart.wautier.eu")

# HOSTs List
ALLOWED_HOSTS = [
    "127.0.0.1",
    "192.168.77.8",
    "192.168.77.97",
    "localhost",
    APP_DOMAIN,
    ".wautier.eu",
]

# Add here your deployment HOSTS
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
    "http://localhost:5085",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:5085",
    f"http://{APP_DOMAIN}",
    f"https://{APP_DOMAIN}",
    f"http://{APP_DOMAIN}:8000",
    f"https://{APP_DOMAIN}:8000",
]

RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# Allow iframe embedding from any origin
X_FRAME_OPTIONS = "ALLOWALL"

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "channels",

    "race",
    "django.contrib.staticfiles",
    "theme_material_kit",
    "django_dyn_api",
    "rest_framework",
    "rest_framework.authtoken",
    "fontawesomefree",
    "django_apscheduler",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

HOME_TEMPLATES = BASE_DIR / "templates"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [HOME_TEMPLATES],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "race.context_processor.active_round_data",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

# For the debug tool bar
INTERNAL_IPS = [
    "127.0.0.1",
    "192.168.77.8",
    "192.168.77.1",
]
# Database
# https://docs.djangoproject.com/en/4.1/ref/settings/#databases

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB"),
            "USER": os.environ.get("POSTGRES_USER"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD"),
            "HOST": os.environ.get("POSTGRES_HOST"),
            "PORT": os.environ.get("POSTGRES_PORT"),
        }
    }

# Password validation
# https://docs.djangoproject.com/en/4.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization
# https://docs.djangoproject.com/en/4.1/topics/i18n/

LANGUAGE_CODE = "en-gb"

TIME_ZONE = "Asia/Bangkok"

USE_I18N = True

USE_TZ = False


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.1/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"

STATICFILES_DIRS = []

# Default primary key field type
# https://docs.djangoproject.com/en/4.1/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_REDIRECT_URL = "Home"
LOGOUT_REDIRECT_URL = "Home"  # Where to redirect after logout

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# __API_GENERATOR__
DYNAMIC_API = {
    # __RULES__
    "Championship": "race.models.Championship",
    "Person": "race.models.Person",
    "Team": "race.models.Team",
    "Round": "race.models.Round",
    "round_pause": "race.models.round_pause",
    "championship_team": "race.models.championship_team",
    "round_team": "race.models.round_team",
    "team_member": "race.models.team_member",
    "Session": "race.models.Session",
    "ChangeLane": "race.models.ChangeLane",
    # __RULES__END
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# _CORS thingy
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
# CORS_ALLOWED_ORIGINS = [
#     "http://toulouse.wautier.eu:8000",
#     # Add other domains you need
# ]
# Allow specific HTTP methods
CORS_ALLOW_METHODS = [
    "GET",
    "OPTIONS",
    "POST",
]

# Allow specific headers
CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]
# __API_GENERATOR__END
# Web sockets

ASGI_APPLICATION = "core.asgi.application"  # Replace your_project

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [("redis", 6379)],
        },
    },
}
# __CELERY__

# __OAUTH_GITHUB__
# DEBUG_TOOLBAR_CONFIG = {
#     "SHOW_TOOLBAR_CALLBACK": lambda r: False,  # disables it
# }
