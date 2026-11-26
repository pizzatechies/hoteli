"""
Django settings for the Hoteli hotel management system.

All deployment-specific values are read from environment variables (or a local
``.env`` file). See ``.env.example`` for the full list.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# --------------------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------------------
DEBUG = env_bool("DEBUG", False)
SECRET_KEY = env("SECRET_KEY") or (
    "django-insecure-dev-only-key-change-me" if DEBUG else None
)
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set when DEBUG is off.")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Render / Railway expose the public hostname through these variables.
for _host_var in ("RENDER_EXTERNAL_HOSTNAME", "RAILWAY_PUBLIC_DOMAIN"):
    _host = env(_host_var)
    if _host:
        ALLOWED_HOSTS.append(_host)
        CSRF_TRUSTED_ORIGINS.append(f"https://{_host}")

# GitHub Codespaces (live demo): trust the forwarded *.app.github.dev address.
_codespace, _codespace_domain = env("CODESPACE_NAME"), env("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
_codespace_url = ""
if _codespace and _codespace_domain:
    ALLOWED_HOSTS.append(f".{_codespace_domain}")
    CSRF_TRUSTED_ORIGINS.append(f"https://*.{_codespace_domain}")
    _codespace_url = f"https://{_codespace}-8000.{_codespace_domain}"

# Public base URL of this site, used for M-Pesa callbacks and links in emails.
SITE_URL = (env("SITE_URL") or _codespace_url or "http://localhost:8000").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Local apps
    "accounts",
    "core",
    "rooms",
    "bookings",
    "mpesa",
    "housekeeping",
    "pos",
    "website",
    "notifications",
    "channel_sync",
    "inventory",
    "finance",
]

MIDDLEWARE = [
    "core.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "accounts.middleware.TwoFactorEnforcementMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "hoteli.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.hotel",
            ],
        },
    },
]

WSGI_APPLICATION = "hoteli.wsgi.application"

if env("DATABASE_URL") or not env("DB_HOST"):
    DATABASES = {
        "default": dj_database_url.config(
            default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
            conn_max_age=600,
        )
    }
else:  # discrete settings, e.g. injected by AWS ECS from Secrets Manager
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": env("DB_HOST"),
            "PORT": env("DB_PORT", "5432"),
            "NAME": env("DB_NAME", "hoteli"),
            "USER": env("DB_USER", "hoteli"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "CONN_MAX_AGE": 600,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {"sslmode": env("DB_SSLMODE", "require")},
        }
    }

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_LOCKOUT_ATTEMPTS = int(env("LOGIN_LOCKOUT_ATTEMPTS", "5"))
LOGIN_LOCKOUT_MINUTES = int(env("LOGIN_LOCKOUT_MINUTES", "15"))
# Staff are signed out after this much inactivity.
SESSION_COOKIE_AGE = int(env("SESSION_IDLE_MINUTES", "240")) * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SECURE_REFERRER_POLICY = "same-origin"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "Africa/Nairobi")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

from django.contrib.messages import constants as message_constants  # noqa: E402

MESSAGE_TAGS = {message_constants.ERROR: "danger"}

# The website builder previews pages in an iframe on the same site.
X_FRAME_OPTIONS = "SAMEORIGIN"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "hoteli",
    }
}

# --------------------------------------------------------------------------------------
# Security (production)
# --------------------------------------------------------------------------------------
if not DEBUG:
    # Behind CloudFront use HTTP_CLOUDFRONT_FORWARDED_PROTO; behind Caddy/nginx/Render the default.
    SECURE_PROXY_SSL_HEADER = (env("SECURE_PROXY_SSL_HEADER_NAME", "HTTP_X_FORWARDED_PROTO"), "https")
    SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", "0"))
    SECURE_CONTENT_TYPE_NOSNIFF = True

# --------------------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
# The display name is replaced by the hotel name (from Settings) when emailing guests.
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "no-reply@hoteli.local")

# --------------------------------------------------------------------------------------
# SMS (console = log only; africastalking = Africa's Talking)
# --------------------------------------------------------------------------------------
SMS_BACKEND = env("SMS_BACKEND", "console").lower()
SMS_USERNAME = env("SMS_USERNAME", "sandbox")
SMS_API_KEY = env("SMS_API_KEY", "")
SMS_SENDER_ID = env("SMS_SENDER_ID", "")

# --------------------------------------------------------------------------------------
# M-Pesa (Safaricom Daraja)
# --------------------------------------------------------------------------------------
# "sandbox" or "production"
MPESA_ENVIRONMENT = env("MPESA_ENVIRONMENT", "sandbox").lower()
MPESA_CONSUMER_KEY = env("MPESA_CONSUMER_KEY", "")
MPESA_CONSUMER_SECRET = env("MPESA_CONSUMER_SECRET", "")
# Lipa Na M-Pesa Online shortcode (Paybill number, or the Head Office/Store number for a till).
MPESA_SHORTCODE = env("MPESA_SHORTCODE", "174379")
# Safaricom's public sandbox passkey. Replace with your production passkey when going live.
MPESA_PASSKEY = env(
    "MPESA_PASSKEY",
    "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919",
)
# "CustomerPayBillOnline" for Paybill, "CustomerBuyGoodsOnline" for Till numbers.
MPESA_TRANSACTION_TYPE = env("MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline")
# For Buy Goods: the till number that receives the money (PartyB). Defaults to the shortcode.
MPESA_TILL_NUMBER = env("MPESA_TILL_NUMBER", "")
# Shortcode used for C2B (customer pays to Paybill with the booking reference as account no.)
MPESA_C2B_SHORTCODE = env("MPESA_C2B_SHORTCODE", "") or MPESA_SHORTCODE
# Public HTTPS base URL Safaricom calls back to. Defaults to SITE_URL.
MPESA_CALLBACK_BASE_URL = (env("MPESA_CALLBACK_BASE_URL") or SITE_URL).rstrip("/")
# Secret path segment that must be present on callback URLs (Safaricom does not sign callbacks).
MPESA_CALLBACK_TOKEN = env("MPESA_CALLBACK_TOKEN", "change-this-callback-token")
# Simulation mode lets you demo the full payment flow without Daraja credentials.
MPESA_SIMULATE = env_bool("MPESA_SIMULATE", not (MPESA_CONSUMER_KEY and MPESA_CONSUMER_SECRET))
# Seconds after which a pending STK push is checked with Daraja's query API.
MPESA_QUERY_AFTER_SECONDS = int(env("MPESA_QUERY_AFTER_SECONDS", "20"))
# Seconds after which an unanswered STK push is treated as timed out.
MPESA_STK_TIMEOUT_SECONDS = int(env("MPESA_STK_TIMEOUT_SECONDS", "180"))
MPESA_REQUEST_TIMEOUT = int(env("MPESA_REQUEST_TIMEOUT", "30"))
# Refunds to guests' phones (Daraja B2C). The security credential is generated in the Daraja portal
# from your initiator password; leave these blank to keep M-Pesa refunds switched off (except in simulation).
MPESA_B2C_SHORTCODE = env("MPESA_B2C_SHORTCODE", "") or MPESA_SHORTCODE
MPESA_B2C_INITIATOR_NAME = env("MPESA_B2C_INITIATOR_NAME", "")
MPESA_B2C_SECURITY_CREDENTIAL = env("MPESA_B2C_SECURITY_CREDENTIAL", "")
MPESA_B2C_COMMAND_ID = env("MPESA_B2C_COMMAND_ID", "BusinessPayment")

# --------------------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "mpesa": {"handlers": ["console"], "level": env("MPESA_LOG_LEVEL", "INFO"), "propagate": False},
        "bookings": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# --------------------------------------------------------------------------------------
# Test runs: fast password hashing and quiet logs
# --------------------------------------------------------------------------------------
import sys  # noqa: E402

if len(sys.argv) > 1 and sys.argv[1] == "test":
    import warnings

    warnings.filterwarnings("ignore", message="No directory at", module="django.core.handlers.base")
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    LOGGING["root"]["level"] = "CRITICAL"
    LOGGING["loggers"]["mpesa"]["level"] = "CRITICAL"
    LOGGING["loggers"]["bookings"]["level"] = "CRITICAL"
    LOGGING["loggers"]["django.request"] = {"handlers": ["console"], "level": "CRITICAL", "propagate": False}
