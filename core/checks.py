"""System checks that guard the deploy. build.sh runs `check --deploy` before migrating,
so an Error here stops a misconfigured release from ever going live."""

from django.conf import settings
from django.core.checks import Error, Tags, register

# The committed fallback that lets `runserver` work without a .env. Public on GitHub.
DEV_SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"


@register(Tags.security, deploy=True)
def check_secret_key_is_set(app_configs, **kwargs) -> list[Error]:
    if settings.SECRET_KEY != DEV_SECRET_KEY:
        return []
    return [
        Error(
            "DJANGO_SECRET_KEY is not set, so the public development key is in use.",
            hint="Set DJANGO_SECRET_KEY in the host's environment.",
            id="shopfront.E001",
        )
    ]
