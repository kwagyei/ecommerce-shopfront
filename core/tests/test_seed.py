import pytest
from django.core.management import call_command

from core.models import Category, Product

pytestmark = pytest.mark.django_db


def test_seed_creates_the_demo_catalog():
    call_command("seed", verbosity=0)
    assert Category.objects.count() == 3
    assert Product.objects.count() == 12


def test_seed_is_idempotent():
    """The deploy runs this on every release; running twice must not duplicate anything."""
    call_command("seed", verbosity=0)
    call_command("seed", verbosity=0)
    assert Product.objects.count() == 12
    assert Category.objects.count() == 3


def test_reseeding_never_overwrites_live_data():
    """Regression: seed used update_or_create, so every deploy reset stock, prices and
    withdrawals to the demo values. Once orders decrement stock, that would let the
    shop sell units it no longer has."""
    call_command("seed", verbosity=0)
    Product.objects.filter(slug="brass-lamp").update(stock=1, price_minor=100, is_active=False)
    Category.objects.filter(slug="desk").update(name="Study")

    call_command("seed", verbosity=0)

    lamp = Product.objects.get(slug="brass-lamp")
    assert (lamp.stock, lamp.price_minor, lamp.is_active) == (1, 100, False)
    assert Category.objects.get(slug="desk").name == "Study"


def test_reseeding_does_not_resurrect_a_deleted_product():
    """Deleting a product in the admin is a decision; the next deploy must respect it."""
    call_command("seed", verbosity=0)
    Product.objects.filter(slug="head-torch").delete()
    call_command("seed", verbosity=0)
    assert not Product.objects.filter(slug="head-torch").exists()


def test_seeded_products_all_have_an_image_and_a_price():
    call_command("seed", verbosity=0)
    for product in Product.objects.all():
        assert product.image.startswith("products/"), product.slug
        assert product.price_minor > 0, product.slug


def test_seed_includes_sold_out_stock_so_that_state_is_visible_in_the_demo():
    call_command("seed", verbosity=0)
    assert Product.objects.filter(stock=0).exists()
