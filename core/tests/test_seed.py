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


def test_seeded_products_all_have_an_image_and_a_price():
    call_command("seed", verbosity=0)
    for product in Product.objects.all():
        assert product.image.startswith("products/"), product.slug
        assert product.price_minor > 0, product.slug


def test_seed_includes_sold_out_stock_so_that_state_is_visible_in_the_demo():
    call_command("seed", verbosity=0)
    assert Product.objects.filter(stock=0).exists()
