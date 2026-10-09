"""Settings used only by the test suite.

    python manage.py test --settings=Somoysondhan.test_settings

Differences from the real settings: an in-memory database, a fast password
hasher, email captured in memory, throttling off, and media written to a temp
directory so a test run never pollutes the project.
"""

import tempfile

from .settings import *  # noqa: F401,F403

DEBUG = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "test@somoysondhan.local"

MEDIA_ROOT = tempfile.mkdtemp(prefix="somoysondhan-test-media-")

# Throttling would make repeated logins in the suite flaky. Views set an explicit
# `throttle_scope`, so the scope rates must still exist — give them huge limits
# rather than removing them (an empty rate raises ImproperlyConfigured).
REST_FRAMEWORK = dict(REST_FRAMEWORK)  # noqa: F405
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "login": "100000/min",
    "register": "100000/min",
    "review": "100000/min",
    "comment": "100000/min",
}

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
}

# Keep logs quiet during tests.
LOGGING["root"]["level"] = "CRITICAL"  # noqa: F405
