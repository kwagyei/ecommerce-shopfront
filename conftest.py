import pytest


@pytest.fixture(autouse=True)
def _test_environment(settings):
    """Two production behaviours that would otherwise break every test.

    SECURE_SSL_REDIRECT turns each request into a 301 because the test client speaks
    plain HTTP, and the hashed staticfiles storage needs a manifest that only exists
    after collectstatic. Both are switched off here rather than weakened in settings.
    """
    settings.SECURE_SSL_REDIRECT = False
    # Production hashing is slow on purpose; tests create users and don't need it.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture(autouse=True)
def _no_real_stripe(monkeypatch):
    """A real test key sits in local .env files. No test may reach Stripe with it: tests
    that need Stripe use the fake in test_checkout.py, which overrides this."""
    from core import payments

    def refuse():
        raise AssertionError("Tests must not call Stripe; use the fake_stripe fixture.")

    monkeypatch.setattr(payments, "stripe_client", refuse)
