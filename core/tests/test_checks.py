from core.checks import DEV_SECRET_KEY, check_secret_key_is_set


def test_the_committed_dev_secret_key_fails_the_deploy_check(settings):
    """Without this, a service created without DJANGO_SECRET_KEY would sign sessions
    and CSRF tokens with a key anyone can read on GitHub. Django only warns (W009)."""
    settings.SECRET_KEY = DEV_SECRET_KEY
    [error] = check_secret_key_is_set(app_configs=None)
    assert error.id == "shopfront.E001"


def test_a_real_secret_key_passes(settings):
    settings.SECRET_KEY = "a-real-generated-value-" + "x" * 40
    assert check_secret_key_is_set(app_configs=None) == []
