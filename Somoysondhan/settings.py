"""
Django settings for Somoysondhan — modern newspaper backend.

Everything deployment-specific comes from the environment (see .env.example),
with safe development defaults so the project still starts out of the box.
"""

from pathlib import Path
from datetime import timedelta

import environ

# --------------------------------------------------------------------------
# Paths / environment
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR / "Somoysondhan"

env = environ.Env(
    DEBUG=(bool, True),
    SECRET_KEY=(str, ""),
    ALLOWED_HOSTS=(list, ["*"]),
    CORS_ALLOW_ALL_ORIGINS=(bool, True),
    CORS_ALLOWED_ORIGINS=(list, []),
    FRONTEND_URL=(str, "http://127.0.0.1:8099"),
    EMAIL=(str, ""),
    EMAIL_PASSWORD=(str, ""),
    TOKEN_TTL_DAYS=(int, 14),
)

# Read .env from the repo root and from the settings package, so the project
# starts whether you run manage.py from the root or from Somoysondhan/.
for candidate in (BASE_DIR / ".env", PROJECT_DIR / ".env"):
    if candidate.exists():
        environ.Env.read_env(str(candidate))

SECRET_KEY = env("SECRET_KEY") or "django-insecure-dev-only-change-me"
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # third party
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "django_filters",
    "drf_spectacular",

    # local
    "reader.apps.ReaderConfig",
    "article.apps.ArticleConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves compressed static files on production (Render).
    # Must come directly after SecurityMiddleware and before everything else.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # CorsMiddleware must sit as high as possible, before CommonMiddleware.
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "Somoysondhan.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "Somoysondhan.wsgi.application"
ASGI_APPLICATION = "Somoysondhan.asgi.application"

# --------------------------------------------------------------------------
# Database — SQLite by default, Postgres via DATABASE_URL
# --------------------------------------------------------------------------
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="sqlite:///" + str(BASE_DIR / "db.sqlite3").replace("\\", "/"),
    )
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# Django REST Framework
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        # Public reads; write access is enforced per view.
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "article.pagination.NewspaperPagination",
    "PAGE_SIZE": 12,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "login": "20/min",
        "register": "10/hour",
        "review": "30/hour",
        "comment": "60/hour",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Somoy Sondhan API",
    "DESCRIPTION": (
        "Backend for the Somoy Sondhan newspaper: articles with a draft/published "
        "workflow, categories, tags, reviews, comments, bookmarks and reader accounts."
    ),
    "VERSION": "2.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
}

# --------------------------------------------------------------------------
# Newspaper behaviour
# --------------------------------------------------------------------------
# How long an authentication token stays valid. Refreshing rotates the key.
TOKEN_TTL = timedelta(days=env("TOKEN_TTL_DAYS"))

# Comments from new readers wait for a moderator unless they are staff.
COMMENTS_REQUIRE_MODERATION = True

# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = env("CORS_ALLOW_ALL_ORIGINS")
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[
        "https://somoysondhan-backend.onrender.com",
        "https://*.onrender.com",
        "https://*.github.io",
        "http://127.0.0.1:8099",
        "http://localhost:8099",
    ],
)

# --------------------------------------------------------------------------
# Internationalisation
# --------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", default="Asia/Dhaka")
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static and media files
# --------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
# MEDIA_ROOT was referenced by urls.py before this setting existed, which made
# `static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)` fail to serve
# uploaded files. Uploads need this.
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # WhiteNoise handles compression and content-addressed file names for
    # the admin and DRF browsable API assets when DEBUG=False on Render.
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# --------------------------------------------------------------------------
# Email (registration confirmation)
# --------------------------------------------------------------------------
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = env("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_HOST_USER = env("EMAIL")
EMAIL_HOST_PASSWORD = env("EMAIL_PASSWORD")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER or "no-reply@somoysondhan.local")

# Where the confirmation link sends the reader afterwards.
FRONTEND_URL = env("FRONTEND_URL").rstrip("/")
BACKEND_URL = env("BACKEND_URL", default="https://somoysondhan-backend.onrender.com").rstrip("/")

# --------------------------------------------------------------------------
# Logging — useful once this runs on Render
# --------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{levelname}] {asctime} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "article": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "reader": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
