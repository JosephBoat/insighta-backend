import os
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SECRET_KEY", "fallback-secret-key")

DEBUG = os.getenv("DEBUG", "False") == "True"

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "profiles",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "core.urls"

WSGI_APPLICATION = "core.wsgi.application"

DATABASES = {
    "default": dj_database_url.parse(
        os.getenv("DATABASE_URL"),
        conn_max_age=0,
        ssl_require=True,
    )
}
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

CORS_ALLOW_ALL_ORIGINS = True
